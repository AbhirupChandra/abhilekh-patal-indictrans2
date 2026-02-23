// ── Configuration ──
const CONFIG = {
    translationServiceUrl: 'http://localhost:5002/translate',
    solrUrl: '/solr/search/select',
    itemBaseUrl: 'https://abhilekh-patal.in/Category/ItemDetails/ItemDetails',
    pageSize: 10,
    solrBatchSize: 100,
    maxQueryLength: 30,
    suggestMinChars: 2,
    suggestMaxResults: 10,
    suggestDebounceMs: 600
};

const LANG_NAMES = {
    'hin_Deva': 'Hindi',
    'eng_Latn': 'English'
};

// ── Per-panel state ──
// Each panel (translated / original) has its own independent pagination state.
function freshPanelState() {
    return {
        query: '',           // the Solr query string for this panel
        synonyms: null,      // Hindi synonym list for OR expansion (original panel only)
        allResults: [],
        totalFound: 0,
        visibleCount: 0,
        solrStart: 0,
        isFetching: false
    };
}

let panels = {
    translated: freshPanelState(),
    original:   freshPanelState()
};
let activeTab = 'translated';
let currentLanguage = 'hin_Deva';
let currentOriginalQuery = '';
let suggestedFromQuery = null; // stores original Hindi input when user clicks a suggestion

// ── DOM refs ──
const $ = id => document.getElementById(id);
const $input          = $('searchInput');
const $btnSearch      = $('btnSearch');
const $loadingArea    = $('loadingArea');
const $translationInfo= $('translationInfo');
const $resultTabs     = $('resultTabs');
const $noResults      = $('noResults');
const $errorBanner    = $('errorBanner');

// Panel DOM lookup
function panelDOM(key) {
    const prefix = key;   // 'translated' or 'original'
    return {
        panel:         $(prefix + 'Panel') || $('panel' + cap(prefix)),
        resultsList:   $(prefix + 'ResultsList'),
        resultCount:   $(prefix + 'ResultCount'),
        queryTag:      $(prefix + 'QueryTag'),
        showMoreWrap:  $(prefix + 'ShowMoreWrapper'),
        btnShowMore:   $(prefix + 'BtnShowMore'),
        showMoreCount: $(prefix + 'ShowMoreCount'),
        noResults:     $(prefix + 'NoResults')
    };
}
function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
    fetchRecordCount();
    setupListeners();
    $('charCounter').style.display = 'none'; // hidden until user types Hindi
});

function detectLanguage(text) {
    // Devanagari Unicode range U+0900–U+097F
    return /[\u0900-\u097F]/.test(text) ? 'hin_Deva' : 'eng_Latn';
}

function applyCharLimit() {
    if (currentLanguage === 'eng_Latn') {
        $input.removeAttribute('maxlength');
        $('charCounter').style.display = 'none';
    } else {
        $input.setAttribute('maxlength', CONFIG.maxQueryLength);
        $('charCounter').style.display = '';
    }
}

function setupListeners() {
    $btnSearch.addEventListener('click', performSearch);
    $input.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
            // If suggestion dropdown is active with a selected item, let the suggestion handler handle it
            const $dropdown = $('suggestionDropdown');
            const activeItem = $dropdown.querySelector('.suggestion-item.active');
            if ($dropdown.classList.contains('visible') && activeItem) return;
            performSearch();
        }
    });

    // Character counter (auto-detect: show only when typing Hindi/Devanagari)
    $input.addEventListener('input', function() {
        const detectedLang = detectLanguage(this.value);
        if (detectedLang === 'eng_Latn') {
            $('charCounter').style.display = 'none';
            $input.removeAttribute('maxlength');
            return;
        }
        $('charCounter').style.display = '';
        $input.setAttribute('maxlength', CONFIG.maxQueryLength);
        const len = this.value.length;
        $('charCount').textContent = len;
        const counter = $('charCounter');
        counter.classList.remove('warning', 'limit');
        if (len >= CONFIG.maxQueryLength) {
            counter.classList.add('limit');
        } else if (len >= CONFIG.maxQueryLength - 3) {
            counter.classList.add('warning');
        }
    });

    // Autocomplete suggestions (debounced)
    // For Hindi input: translate to English, then fetch BOTH Hindi + English suggestions
    const debouncedSuggest = debounce(async function() {
        // Cancel previous suggestion cycle
        if (suggestAbortController) suggestAbortController.abort();
        suggestAbortController = new AbortController();
        const signal = suggestAbortController.signal;

        const val = $input.value.trim();
        if (val.length < CONFIG.suggestMinChars) {
            hideSuggestions();
            return;
        }

        const isHindi = detectLanguage(val) !== 'eng_Latn';

        if (isHindi) {
            // Step 1: Translate Hindi to English
            let translatedVal = null;
            try {
                const result = await translateQuery(val, detectLanguage(val), signal);
                if ($input.value.trim() !== val) return; // stale check
                translatedVal = result.translated;
                // Guard against empty translation
                if (!translatedVal || !translatedVal.trim()) translatedVal = null;
            } catch (e) {
                // Translation failed — will only show Hindi suggestions
            }

            // Step 2: Fetch BOTH Hindi and English suggestions in parallel
            const hindiPromise = fetchSuggestions(val, signal);
            const englishPromise = translatedVal
                ? fetchSuggestions(translatedVal, signal)
                : Promise.resolve([]);
            const [hindiTitles, englishTitles] = await Promise.all([hindiPromise, englishPromise]);

            if ($input.value.trim() !== val) return; // stale check

            // Step 3: Merge results — Hindi first, then English (deduplicated)
            const seen = new Set();
            const merged = [];
            for (const item of hindiTitles) {
                if (!seen.has(item.title.toLowerCase())) {
                    seen.add(item.title.toLowerCase());
                    merged.push(item);
                }
            }
            for (const item of englishTitles) {
                if (!seen.has(item.title.toLowerCase())) {
                    seen.add(item.title.toLowerCase());
                    merged.push(item);
                }
            }

            renderSuggestions(merged, val, translatedVal);
        } else {
            // English input — fetch directly
            const titles = await fetchSuggestions(val, signal);
            if ($input.value.trim() === val) {
                renderSuggestions(titles, val, null);
            }
        }
    }, CONFIG.suggestDebounceMs);

    $input.addEventListener('input', debouncedSuggest);

    // Keyboard navigation for suggestions
    $input.addEventListener('keydown', function(e) {
        const $dropdown = $('suggestionDropdown');
        const items = $dropdown.querySelectorAll('.suggestion-item');
        if (!items.length || !$dropdown.classList.contains('visible')) return;

        const activeItem = $dropdown.querySelector('.suggestion-item.active');
        let activeIndex = activeItem ? parseInt(activeItem.dataset.index) : -1;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            activeIndex = Math.min(activeIndex + 1, items.length - 1);
            items.forEach(item => item.classList.remove('active'));
            items[activeIndex].classList.add('active');
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            activeIndex = Math.max(activeIndex - 1, 0);
            items.forEach(item => item.classList.remove('active'));
            items[activeIndex].classList.add('active');
        } else if (e.key === 'Escape') {
            hideSuggestions();
        } else if (e.key === 'Enter' && activeIndex >= 0) {
            e.preventDefault();
            const selectedText = items[activeIndex].querySelector('.suggestion-text').textContent;
            suggestedFromQuery = $input.value.trim(); // capture original query before overwriting
            $input.value = selectedText;
            hideSuggestions();
            performSearch();
        }
    });

    // Click on suggestion item
    $('suggestionDropdown').addEventListener('click', function(e) {
        const item = e.target.closest('.suggestion-item');
        if (!item) return;
        const selectedText = item.querySelector('.suggestion-text').textContent;
        suggestedFromQuery = $input.value.trim(); // capture original query before overwriting
        $input.value = selectedText;
        hideSuggestions();
        performSearch();
    });

    // Click outside to close suggestions
    document.addEventListener('click', function(e) {
        if (!e.target.closest('.search-card') && !e.target.closest('.suggestion-dropdown')) {
            hideSuggestions();
        }
    });

    // Tab switching
    document.querySelectorAll('.result-tab').forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    // Show More for each panel
    $('translatedBtnShowMore').addEventListener('click', () => showMore('translated'));
    $('originalBtnShowMore').addEventListener('click', () => showMore('original'));
}

function switchTab(tabKey) {
    activeTab = tabKey;
    document.querySelectorAll('.result-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tabKey));
    $('panelTranslated').classList.toggle('active', tabKey === 'translated');
    $('panelOriginal').classList.toggle('active', tabKey === 'original');
}

// ── Search Flow ──
async function performSearch() {
    const query = $input.value.trim();
    if (!query) return;
    hideSuggestions();

    // Auto-detect language from input text
    // If suggestion was clicked from a Hindi search, restore Hindi context
    let originalHindiQuery = null;
    if (suggestedFromQuery && detectLanguage(suggestedFromQuery) !== 'eng_Latn') {
        currentLanguage = detectLanguage(suggestedFromQuery);
        originalHindiQuery = suggestedFromQuery;
    } else {
        currentLanguage = detectLanguage(query);
    }
    suggestedFromQuery = null; // reset after use
    applyCharLimit();

    // Character limit validation (only for non-English — they use translation API)
    if (currentLanguage !== 'eng_Latn' && !originalHindiQuery && query.length > CONFIG.maxQueryLength) {
        showError('Query must be ' + CONFIG.maxQueryLength + ' characters or fewer. Current: ' + query.length + ' characters.');
        return;
    }

    resetUI();
    $loadingArea.style.display = 'block';

    try {
        let translatedQuery = query;
        let isNonEnglish = currentLanguage !== 'eng_Latn';

        // 1. Translate if non-English
        let selectedTitle = null; // only set when user clicked a suggestion
        if (isNonEnglish) {
            if (originalHindiQuery) {
                // User clicked a suggestion from Hindi search
                selectedTitle = query; // the clicked suggestion title (English or Hindi)

                // Always translate the original short Hindi query for the "Translated" display
                try {
                    const result = await translateQuery(originalHindiQuery, currentLanguage);
                    translatedQuery = result.translated;
                    if (!translatedQuery || !translatedQuery.trim()) {
                        translatedQuery = originalHindiQuery;
                    }
                } catch (e) {
                    translatedQuery = originalHindiQuery;
                }
            } else {
                // Direct search (Enter/button) — translate typed query
                const result = await translateQuery(query, currentLanguage);
                translatedQuery = result.translated;
                // Guard against empty translation — fallback to original query
                if (!translatedQuery || !translatedQuery.trim()) {
                    translatedQuery = query;
                }
            }
        }

        const originalQuery = originalHindiQuery || query;
        currentOriginalQuery = originalQuery;
        showTranslationInfo(originalQuery, translatedQuery, isNonEnglish, selectedTitle);

        // 2. Expand Hindi synonyms (if non-English) and fire both Solr queries in parallel
        // Route queries based on what language the clicked suggestion is in
        let searchTranslatedQuery = translatedQuery;   // default: English translation
        let searchOriginalQuery   = originalQuery;      // default: short Hindi typed query

        if (selectedTitle) {
            if (detectLanguage(selectedTitle) === 'eng_Latn') {
                // English suggestion clicked → left panel searches full English title
                searchTranslatedQuery = selectedTitle;
            } else {
                // Hindi suggestion clicked → right panel searches full Hindi title
                searchOriginalQuery = selectedTitle;
            }
        }

        const synonyms = isNonEnglish ? await expandQuery(searchOriginalQuery) : null;
        const translatedPromise = searchSolr(searchTranslatedQuery, 0);
        const originalPromise   = isNonEnglish ? searchSolr(searchOriginalQuery, 0, synonyms) : null;

        const translatedData = await translatedPromise;
        const originalData   = originalPromise ? await originalPromise : null;

        $loadingArea.style.display = 'none';

        // 3. Set up translated panel
        const tp = panels.translated;
        tp.query       = searchTranslatedQuery;
        tp.totalFound  = translatedData.response.numFound;
        tp.allResults  = translatedData.response.docs;
        tp.solrStart   = tp.allResults.length;
        tp.visibleCount = 0;

        // 4. Set up original panel
        const op = panels.original;
        if (originalData) {
            op.query       = searchOriginalQuery;
            op.synonyms    = synonyms;  // store for "Show More" pagination
            op.totalFound  = originalData.response.numFound;
            op.allResults  = originalData.response.docs;
            op.solrStart   = op.allResults.length;
            op.visibleCount = 0;
        }

        // Both empty?
        if (tp.totalFound === 0 && (!originalData || op.totalFound === 0)) {
            $noResults.style.display = 'block';
            return;
        }

        // Show tabs (only if non-English, otherwise single panel)
        if (isNonEnglish) {
            $resultTabs.style.display = 'flex';
            $('tabTranslated').innerHTML = 'Translated Results <span class="tab-count">' + tp.totalFound.toLocaleString() + '</span>';
            $('tabOriginal').innerHTML = 'Original (' + LANG_NAMES[currentLanguage] + ') Results <span class="tab-count">' + op.totalFound.toLocaleString() + '</span>';
        } else {
            $resultTabs.style.display = 'none';
        }

        // Populate translated panel header
        $('translatedResultCount').textContent = tp.totalFound.toLocaleString();
        // Show query tag without stop words for multi-word English queries
        const displayTranslatedQuery = (detectLanguage(searchTranslatedQuery) === 'eng_Latn' && searchTranslatedQuery.trim().split(/\s+/).length > 1)
            ? removeStopWords(searchTranslatedQuery)
            : searchTranslatedQuery;
        $('translatedQueryTag').textContent = 'title:"' + displayTranslatedQuery + '"';

        if (tp.totalFound > 0) {
            showMore('translated');
        } else {
            $('translatedNoResults').style.display = 'block';
        }

        // Populate original panel
        if (isNonEnglish) {
            $('originalResultCount').textContent = op.totalFound.toLocaleString();
            if (synonyms && synonyms.length > 1) {
                $('originalQueryTag').textContent = 'title:(' + synonyms.map(function(s) { return '"' + s + '"'; }).join(' OR ') + ')';
            } else {
                $('originalQueryTag').textContent = 'title:"' + searchOriginalQuery + '"';
            }
            if (op.totalFound > 0) {
                showMore('original');
            } else {
                $('originalNoResults').style.display = 'block';
            }
        }

        // Choose default tab:
        // - Hindi suggestion clicked → show Original (Hindi) panel first
        // - Otherwise → show Translated panel first; if empty show Original
        const hindiSuggestionClicked = selectedTitle && detectLanguage(selectedTitle) !== 'eng_Latn';
        if (hindiSuggestionClicked && isNonEnglish && op.totalFound > 0) {
            switchTab('original');
        } else if (tp.totalFound > 0) {
            switchTab('translated');
        } else if (isNonEnglish && op.totalFound > 0) {
            switchTab('original');
        }

        // Make both panels exist in DOM (active one is visible via CSS)
        $('panelTranslated').style.removeProperty('display');
        $('panelOriginal').style.removeProperty('display');

    } catch (err) {
        $loadingArea.style.display = 'none';
        showError(err.message);
    }
}

// ── Translation ──
async function translateQuery(text, srcLang, signal) {
    const opts = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, src_lang: srcLang, tgt_lang: 'eng_Latn' })
    };
    if (signal) opts.signal = signal;
    const res = await fetch(CONFIG.translationServiceUrl, opts);
    if (!res.ok) throw new Error('Translation service unavailable');
    const data = await res.json();
    if (!data.success) throw new Error('Translation failed: ' + (data.error || 'Unknown'));
    return data;
}

// ── Synonym Expansion ──
async function expandQuery(text) {
    try {
        const expandUrl = CONFIG.translationServiceUrl.replace('/translate', '/expand');
        const res = await fetch(expandUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text })
        });
        if (!res.ok) return null;
        const data = await res.json();
        if (data.success && data.has_synonyms && data.synonyms.length > 1) {
            return data.synonyms;
        }
        return null;
    } catch (e) {
        console.warn('Synonym expansion failed, using original query:', e);
        return null;
    }
}

// ── Autocomplete Suggestions ──
function debounce(fn, delay) {
    let timer;
    return function(...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

let suggestAbortController = null;

async function fetchSuggestions(partial, signal) {
    // Helper to extract unique titles from Solr docs
    function extractTitles(docs, seen, fuzzy) {
        const results = [];
        for (const doc of docs) {
            const t = Array.isArray(doc['dc.title']) ? doc['dc.title'][0] : doc['dc.title'];
            if (t && !seen.has(t.toLowerCase())) {
                seen.add(t.toLowerCase());
                results.push({ title: t, fuzzy: fuzzy });
                if (results.length >= CONFIG.suggestMaxResults) break;
            }
        }
        return results;
    }

    try {
        const seen = new Set();

        // Phase 1: Exact prefix match
        const params = new URLSearchParams({
            'q':     'dc.title:' + partial + '*',
            'fq':    'search.resourcetype:Item',
            'fl':    'dc.title',
            'rows':  100,
            'wt':    'json'
        });
        const res = await fetch(CONFIG.solrUrl + '?' + params, { signal: signal });
        if (!res.ok) return [];
        const data = await res.json();
        const docs = data.response.docs || [];
        const titles = extractTitles(docs, seen, false);

        // Phase 2: If no prefix results and input >= 3 chars, try fuzzy match via eDisMax
        if (titles.length === 0 && partial.length >= 3) {
            const fuzzyTerms = partial.split(/\s+/).map(function(term) {
                return term + '~1';
            }).join(' ');
            const fuzzyParams = new URLSearchParams({
                'q':        fuzzyTerms,
                'defType':  'edismax',
                'qf':       'dc.title',
                'mm':       '1',
                'fq':       'search.resourcetype:Item',
                'fl':       'dc.title',
                'rows':     100,
                'wt':       'json'
            });
            const fuzzyRes = await fetch(CONFIG.solrUrl + '?' + fuzzyParams, { signal: signal });
            if (fuzzyRes.ok) {
                const fuzzyData = await fuzzyRes.json();
                const fuzzyDocs = fuzzyData.response.docs || [];
                const fuzzyTitles = extractTitles(fuzzyDocs, seen, true);
                return fuzzyTitles;
            }
        }

        return titles;
    } catch (e) {
        if (e.name === 'AbortError') return [];
        return [];
    }
}

function renderSuggestions(suggestions, partial, altPartial) {
    const $dropdown = $('suggestionDropdown');
    if (!suggestions.length) {
        $dropdown.classList.remove('visible');
        $dropdown.innerHTML = '';
        return;
    }

    // Primary highlight regex (e.g. Hindi partial for Hindi titles)
    const escaped = partial.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp('(' + escaped + ')', 'gi');

    // Alternate highlight regex (e.g. English translated text for English titles)
    let altRegex = null;
    if (altPartial) {
        const altEscaped = altPartial.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        altRegex = new RegExp('(' + altEscaped + ')', 'gi');
    }

    let html = '<div class="suggestion-header">Did you mean:</div>';

    html += suggestions.map((item, i) => {
        const plainTitle = escapeHtml(item.title);
        // Try primary highlight first; if no match and alt exists, try alt
        let highlighted = plainTitle.replace(regex, '<mark>$1</mark>');
        if (altRegex && highlighted === plainTitle) {
            highlighted = plainTitle.replace(altRegex, '<mark>$1</mark>');
        }
        const fuzzyClass = item.fuzzy ? ' fuzzy-match' : '';
        return '<div class="suggestion-item' + fuzzyClass + '" data-index="' + i + '">' +
               '<span class="suggestion-icon">&#128269;</span>' +
               '<span class="suggestion-text">' + highlighted + '</span>' +
               '</div>';
    }).join('');

    $dropdown.innerHTML = html;
    $dropdown.classList.add('visible');
}

function hideSuggestions() {
    const $dropdown = $('suggestionDropdown');
    $dropdown.classList.remove('visible');
    $dropdown.innerHTML = '';
}

// ── Solr Search ──
async function searchSolr(query, start, synonyms) {
    let qValue;
    if (synonyms && synonyms.length > 1) {
        // Build OR query from synonym list for expanded search
        const terms = synonyms.map(function(s) { return '"' + s + '"'; }).join(' OR ');
        qValue = 'dc.title:(' + terms + ')';
    } else {
        // Multi-word English queries: remove stop words, use fuzzy AND
        // Single-word and Hindi queries: exact phrase match
        const isEnglish = detectLanguage(query) === 'eng_Latn';
        const cleaned = isEnglish ? removeStopWords(query) : query;
        const words = cleaned.trim().split(/\s+/);
        if (isEnglish && words.length > 1) {
            const fuzzyTerms = words.map(function(w) { return w + '~1'; }).join(' AND ');
            qValue = 'dc.title:(' + fuzzyTerms + ')';
        } else {
            qValue = 'dc.title:"' + query + '"';
        }
    }
    const params = new URLSearchParams({
        'q':     qValue,
        'fq':    'search.resourcetype:Item',
        'q.op':  'AND',
        'fl':    'dc.title,search.resourceid,dc.identifier,dc.date.issued,dc.identifier.fileName,dc.subject.branch',
        'start': start,
        'rows':  CONFIG.solrBatchSize,
        'wt':    'json'
    });
    const res = await fetch(CONFIG.solrUrl + '?' + params);
    if (!res.ok) throw new Error('Solr search failed (HTTP ' + res.status + ')');
    return await res.json();
}

// ── Show More (per panel) ──
async function showMore(panelKey) {
    const state = panels[panelKey];
    const dom   = panelDOM(panelKey);

    // Fetch more from Solr if buffer low
    if (state.visibleCount + CONFIG.pageSize > state.allResults.length && state.solrStart < state.totalFound) {
        if (state.isFetching) return;
        state.isFetching = true;
        dom.btnShowMore.textContent = 'Loading...';
        dom.btnShowMore.disabled = true;
        try {
            const solrData = await searchSolr(state.query, state.solrStart, state.synonyms);
            const newDocs = solrData.response.docs;
            state.allResults = state.allResults.concat(newDocs);
            state.solrStart += newDocs.length;
            if (newDocs.length < CONFIG.solrBatchSize) state.solrStart = state.totalFound;
        } catch (err) {
            showError('Failed to load more: ' + err.message);
            dom.btnShowMore.textContent = 'Show More';
            dom.btnShowMore.disabled = false;
            state.isFetching = false;
            return;
        }
        dom.btnShowMore.textContent = 'Show More';
        dom.btnShowMore.disabled = false;
        state.isFetching = false;
    }

    const nextBatch = state.allResults.slice(state.visibleCount, state.visibleCount + CONFIG.pageSize);

    nextBatch.forEach((doc, i) => {
        const globalIndex = state.visibleCount + i + 1;
        const title      = field(doc, 'dc.title') || '[No title]';
        const resourceId = field(doc, 'search.resourceid') || '';
        const identifier = field(doc, 'dc.identifier') || '';
        const dateIssued = field(doc, 'dc.date.issued') || '';
        const fileName   = field(doc, 'dc.identifier.fileName') || '';
        const branch     = field(doc, 'dc.subject.branch') || '';
        const year       = dateIssued ? dateIssued.substring(0, 4) : '';
        const itemUrl    = CONFIG.itemBaseUrl + '?itemId=' + encodeURIComponent(resourceId);

        let metaHtml = '';
        if (identifier) metaHtml += '<span class="meta-tag"><span class="meta-label">Identifier:</span> ' + escapeHtml(identifier) + '</span>';
        if (year)       metaHtml += '<span class="meta-tag"><span class="meta-label">Year:</span> ' + escapeHtml(year) + '</span>';
        if (fileName)   metaHtml += '<span class="meta-tag"><span class="meta-label">File:</span> ' + escapeHtml(fileName) + '</span>';
        if (branch)     metaHtml += '<span class="meta-tag"><span class="meta-label">Branch:</span> ' + escapeHtml(branch) + '</span>';

        const card = document.createElement('div');
        card.className = 'result-card';
        card.innerHTML =
            '<div class="result-num">' + globalIndex + '</div>' +
            '<div class="result-body">' +
                '<a href="' + escapeHtml(itemUrl) + '" target="_blank" rel="noopener">' + escapeHtml(title) + '</a>' +
                (metaHtml ? '<div class="result-meta-row">' + metaHtml + '</div>' : '') +
            '</div>';

        dom.resultsList.appendChild(card);
    });

    state.visibleCount += nextBatch.length;
    updatePanelShowMore(panelKey);
}

function updatePanelShowMore(panelKey) {
    const state = panels[panelKey];
    const dom   = panelDOM(panelKey);
    const remaining = state.totalFound - state.visibleCount;

    if (remaining > 0) {
        dom.showMoreWrap.style.display = 'block';
        dom.showMoreCount.textContent = 'Showing ' + state.visibleCount.toLocaleString() + ' of ' + state.totalFound.toLocaleString() + ' results';
    } else {
        dom.showMoreWrap.style.display = 'none';
        if (state.visibleCount > 0) {
            dom.showMoreCount.textContent = 'Showing all ' + state.totalFound.toLocaleString() + ' results';
            dom.showMoreCount.style.display = 'block';
            dom.showMoreCount.parentElement.style.display = 'block';
        }
    }
}

// ── Translation Info ──
function showTranslationInfo(original, translated, isNonEnglish, selectedTitle) {
    const $ti = $('translationInfo');
    if (isNonEnglish) {
        let html =
            '<p><strong>Original (' + LANG_NAMES[currentLanguage] + '):</strong> ' + escapeHtml(original) + '</p>' +
            '<p><strong>Translated (English):</strong> <span class="translated-text">' + escapeHtml(translated) + '</span></p>';
        if (selectedTitle) {
            html += '<p><strong>Selected title:</strong> ' + escapeHtml(selectedTitle) + '</p>';
        }
        $ti.innerHTML = html;
    } else {
        $ti.innerHTML =
            '<p><strong>Query:</strong> ' + escapeHtml(original) + '</p>';
    }
    $ti.style.display = 'block';
}

function showError(msg) {
    $('errorBanner').textContent = 'Error: ' + msg;
    $('errorBanner').style.display = 'block';
}

function resetUI() {
    $loadingArea.style.display = 'none';
    $('translationInfo').style.display = 'none';
    $resultTabs.style.display = 'none';
    $noResults.style.display = 'none';
    $('errorBanner').style.display = 'none';

    // Reset both panels
    ['translated', 'original'].forEach(key => {
        panels[key] = freshPanelState();
        const dom = panelDOM(key);
        dom.resultsList.innerHTML = '';
        dom.resultCount.textContent = '0';
        dom.queryTag.textContent = '';
        dom.showMoreWrap.style.display = 'none';
        dom.showMoreCount.textContent = '';
        dom.noResults.style.display = 'none';
    });

    // Reset tabs to translated active
    switchTab('translated');
}

// ── Stop Words ──
const STOP_WORDS = new Set(['the','a','an','of','in','on','at','to','for','and','or','is','was','are','were','be','been','by','with','from','as','it','its','that','this','not','but','no']);

function removeStopWords(text) {
    return text.trim().split(/\s+/).filter(function(w) { return !STOP_WORDS.has(w.toLowerCase()); }).join(' ');
}

// ── Utilities ──
function field(doc, name) {
    const v = doc[name];
    if (v == null) return '';
    return Array.isArray(v) ? v[0] : v;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(String(str)));
    return div.innerHTML;
}

// ── Record count for update bar ──
async function fetchRecordCount() {
    try {
        const params = new URLSearchParams({ 'q': '*:*', 'fq': 'search.resourcetype:Item', 'rows': 0, 'wt': 'json' });
        const res = await fetch(CONFIG.solrUrl + '?' + params);
        const data = await res.json();
        const count = data.response.numFound;
        const today = new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
        $('updateBar').textContent = 'Last Updated: ' + count.toLocaleString() + ' records on ' + today;
    } catch (e) {
        $('updateBar').textContent = 'Last Updated: --';
    }
}
