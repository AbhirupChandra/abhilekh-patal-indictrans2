# Abhilekh Patal — Multilingual Search: Complete Project Blueprint

> **Purpose of this document:** This file contains every algorithm, data flow, edge case, and implementation detail needed to **replicate this entire project in any programming language** (React, Angular, Vue, Java, Go, .NET, etc.) without reading a single line of the original source code.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [API Contracts](#3-api-contracts)
4. [Solr Schema & Queries](#4-solr-schema--queries)
5. [Language Detection](#5-language-detection)
6. [Autocomplete Suggestions](#6-autocomplete-suggestions)
7. [Search Flow](#7-search-flow)
8. [Translation Service](#8-translation-service)
9. [Synonym Expansion](#9-synonym-expansion)
10. [UI Components & Layout](#10-ui-components--layout)
11. [Pagination (Show More)](#11-pagination-show-more)
12. [Edge Cases & Bug Fixes](#12-edge-cases--bug-fixes)
13. [Configuration Reference](#13-configuration-reference)
14. [Data Structures](#14-data-structures)

---

## 1. Project Overview

A multilingual document search interface for India's National Archives (Abhilekh Patal). Users can search in **Hindi (Devanagari script)** or **English**. Hindi queries are automatically translated to English using an offline AI model (IndicTrans2), enabling cross-language retrieval from an English-indexed Apache Solr database.

### Key Features
- **Auto-detect language** from input (Devanagari → Hindi, Latin → English)
- **Autocomplete suggestions** with 2-phase lookup (exact prefix + fuzzy fallback)
- **Dual-language suggestions** for Hindi input (Hindi titles + translated English titles)
- **Dual-panel results** for Hindi searches (Translated Results + Original Hindi Results)
- **Single-panel results** when a suggestion is clicked (exact 1 document)
- **Hindi synonym expansion** (e.g., "वाराणसी" also searches "काशी", "बनारस")
- **Fuzzy English search** with stop-word removal
- **Translation timeout** (5 seconds) with graceful fallback
- **Offline AI translation** — no external API calls after model download
- **Usage tracking** — SQLite-based analytics per IP/query

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                         BROWSER                               │
│                                                                │
│  ┌──────────┐  ┌───────────────┐  ┌─────────────────────┐    │
│  │ Search   │→ │ Autocomplete  │→ │ Results Display      │    │
│  │ Input    │  │ Suggestions   │  │ (Single or Dual Tab) │    │
│  └──────────┘  └───────────────┘  └─────────────────────┘    │
│       │              │                       │                 │
└───────┼──────────────┼───────────────────────┼─────────────────┘
        │              │                       │
        ▼              ▼                       ▼
   ┌─────────┐   ┌──────────┐          ┌──────────┐
   │/translate│   │ /solr/   │          │ /solr/   │
   │/expand   │   │ select   │          │ select   │
   │(port 5002)  │(port 8983)│          │(port 8983)│
   └─────────┘   └──────────┘          └──────────┘
   Translation    Suggestions            Search
   Service        (prefix/fuzzy)         Results
```

### Components
| Component | Technology | Port | Purpose |
|-----------|-----------|------|---------|
| Frontend | HTML + CSS + vanilla JS | 80 (via Nginx) | Search UI |
| Translation API | Python Flask + IndicTrans2 | 5002 | Hindi→English translation + synonym expansion |
| Search Engine | Apache Solr | 8983 | Full-text document search |
| Reverse Proxy | Nginx | 80 | Routes requests, serves static files |

---

## 3. API Contracts

### 3.1 POST /translate

Translates Indic text to English.

**Request:**
```json
{
  "text": "गांधी",
  "src_lang": "hin_Deva",
  "tgt_lang": "eng_Latn"
}
```

**Response (success):**
```json
{
  "success": true,
  "original": "गांधी",
  "translated": "Gandhi",
  "src_lang": "hin_Deva",
  "tgt_lang": "eng_Latn",
  "processing_time_ms": 118.8,
  "model": "IndicTrans2 (ai4bharat/indictrans2-indic-en-dist-200M)",
  "mode": "OFFLINE (CPU)"
}
```

**Response (error):**
```json
{
  "success": false,
  "error": "Query exceeds maximum length of 30 characters. Received: 35."
}
```

**Validation rules:**
- `text` is required
- `text.length` must be ≤ 30 characters (server enforced)
- `src_lang` must be in supported languages list (defaults to `hin_Deva`)
- `tgt_lang` defaults to `eng_Latn`

**Supported language codes (FLORES):**
```
hin_Deva, ben_Beng, guj_Gujr, kan_Knda, mal_Mlym,
mar_Deva, ory_Orya, pan_Guru, tam_Taml, tel_Telu, eng_Latn
```

### 3.2 POST /expand

Returns Hindi synonyms for a word (e.g., city name variants).

**Request:**
```json
{ "text": "वाराणसी" }
```

**Response:**
```json
{
  "success": true,
  "original": "वाराणसी",
  "synonyms": ["वाराणसी", "काशी", "बनारस", "बेनारस"],
  "has_synonyms": true
}
```

**Logic:** Exact dictionary lookup. Returns empty array if no synonyms found.

### 3.3 GET /solr/search/select

Standard Solr select endpoint. All Solr queries use these common parameters:

```
fq=search.resourcetype:Item
q.op=AND
fl=dc.title,search.resourceid,dc.identifier,dc.date.issued,dc.identifier.fileName,dc.subject.branch
wt=json
```

---

## 4. Solr Schema & Queries

### Document Fields

| Solr Field | Type | Description | Example |
|-----------|------|-------------|---------|
| `dc.title` | text (multivalued) | Document title | "Gandhi" |
| `search.resourceid` | string | Unique document UUID | "abc-123-def" |
| `dc.identifier` | string | Archive identifier | "PR_000001673540" |
| `dc.date.issued` | string | Year of document | "1957" |
| `dc.identifier.fileName` | string | File reference | "Prog., Nos. 21-48 D.3, 1957" |
| `dc.subject.branch` | string | Archive branch | "Home" |
| `search.resourcetype` | string | Always filter by `Item` | "Item" |

### Query Types (5 modes)

#### Mode 1: ResourceId lookup (suggestion clicks)
```
q=search.resourceid:<UUID>
```
Used when user clicks a suggestion. Returns exactly 1 document. Most reliable.

#### Mode 2: Synonym OR expansion (Hindi with synonyms)
```
q=dc.title:("वाराणसी" OR "काशी" OR "बनारस" OR "बेनारस")
```
Used when synonym dictionary returns multiple variants for the Hindi query.

#### Mode 3: Fuzzy AND search (multi-word English typed queries)
```
q=dc.title:(gandhi~1 AND memorial~1)
```
Used for typed English queries with 2+ words. Each word gets `~1` (edit distance 1) for typo tolerance. Stop words and non-alpha characters are removed first.

#### Mode 4: Exact phrase (Hindi, single-word English, suggestion clicks without resourceId)
```
q=dc.title:"गांधी"
```
Used for Hindi queries (exact Devanagari phrase) and single-word English queries.

#### Mode 5: Prefix wildcard (autocomplete suggestions)
```
q=dc.title:gandhi*
```
Phase 1 of autocomplete. Followed by fuzzy fallback if zero results.

### Query Selection Logic (pseudocode)
```
if resourceId is provided:
    use Mode 1 (resourceid lookup)
elif synonyms array has 2+ entries:
    use Mode 2 (synonym OR)
elif query is English AND has 2+ words AND not exact-match flag:
    sanitize words (remove non-alpha, stop words, single chars)
    if 2+ words remain:
        use Mode 3 (fuzzy AND)
    else:
        use Mode 4 (exact phrase)
else:
    use Mode 4 (exact phrase)
```

---

## 5. Language Detection

**Algorithm:** Check if any character in the input falls within the Devanagari Unicode range.

```
Devanagari range: U+0900 to U+097F
Regex: /[\u0900-\u097F]/

If ANY character matches → language = "hin_Deva" (Hindi)
Otherwise → language = "eng_Latn" (English)
```

**Used in:**
- Determining whether to translate the query
- Showing/hiding character counter (only for Hindi)
- Routing suggestion clicks to correct panel
- Choosing default tab after search

---

## 6. Autocomplete Suggestions

### Trigger
- Fires on every input change after debounce (600ms)
- Minimum 2 characters required
- Each new keystroke cancels the previous suggestion request (AbortController)

### Flow for English Input
```
1. User types "gandhi"
2. Debounce 600ms
3. fetchSuggestions("gandhi") → Solr
4. Render suggestions
```

### Flow for Hindi Input (parallel, non-blocking)
```
1. User types "गांधी"
2. Debounce 600ms
3. IMMEDIATELY fire fetchSuggestions("गांधी") for Hindi titles
4. IN PARALLEL, call translateQuery("गांधी") with 5s timeout
5. If translation succeeds → "Gandhi" → fetchSuggestions("Gandhi") for English titles
6. If translation fails/times out → proceed with Hindi suggestions only
7. Await all promises
8. Merge: Hindi suggestions first, then English (deduplicated by lowercase title)
9. Render merged suggestions
```

**CRITICAL EDGE CASE:** Hindi suggestions must NOT be blocked by translation. The Hindi Solr query fires immediately. Translation runs in parallel. If translation hangs, Hindi suggestions still appear.

### fetchSuggestions() — 2-Phase Lookup

**Phase 1: Exact prefix match**
```
q=dc.title:<partial>*
rows=100
fl=dc.title,search.resourceid
fq=search.resourcetype:Item
```
Extracts unique titles (deduplicated by lowercase), capped at 10 results.

**Phase 2: Fuzzy fallback (only if Phase 1 returns 0 results AND input ≥ 3 chars)**
```
q=<word1>~1 <word2>~1 ...
defType=edismax
qf=dc.title
mm=1
rows=100
fl=dc.title,search.resourceid
fq=search.resourcetype:Item
```
Each word gets edit distance 1 for typo correction. Results are marked as `fuzzy: true`.

### Suggestion Data Structure
Each suggestion item contains:
```
{
  title: "Full Document Title",
  resourceId: "solr-uuid-here",
  fuzzy: false  // true if from Phase 2
}
```

### Suggestion Rendering
- Header: "Did you mean:"
- Each item shows: 🔍 icon + title with matched portion highlighted in `<mark>` tags
- Highlighting: try primary regex (user's typed text) first; if no match and alternate exists (translated text), try alternate regex
- Fuzzy matches get a slightly different background color

### Suggestion Interaction
- **Click** or **Enter on keyboard-selected item**:
  1. Store `suggestedFromQuery` = original input text (before overwriting)
  2. Store `suggestedResourceId` = the `data-resourceid` attribute of clicked item
  3. Set input value to the clicked title
  4. Hide dropdown
  5. Call `performSearch()`
- **Keyboard navigation**: ArrowUp/ArrowDown to navigate, Escape to close
- **Click outside**: closes dropdown

---

## 7. Search Flow

### Entry Points
1. **Enter key** (when no suggestion is keyboard-selected)
2. **Search button click**
3. **Suggestion click** (or Enter on keyboard-selected suggestion)

### Full Search Algorithm

```
performSearch():
  query = input.value.trim()
  if empty → return

  // Detect context
  clickedResourceId = suggestedResourceId  (captured before reset)

  if suggestedFromQuery exists AND is Hindi:
      currentLanguage = Hindi
      originalHindiQuery = suggestedFromQuery
  else:
      currentLanguage = detectLanguage(query)

  Reset suggestedFromQuery and suggestedResourceId to null

  // Character limit (Hindi only, not for suggestion clicks)
  if Hindi AND no originalHindiQuery AND query.length > 30:
      show error → return

  resetUI()
  show loading spinner

  // Step 1: Translate if non-English
  selectedTitle = null
  isNonEnglish = (currentLanguage != English)

  if isNonEnglish:
      if originalHindiQuery exists:
          // User clicked a suggestion from Hindi search
          selectedTitle = query  // the clicked suggestion title
          try:
              translatedQuery = translate(originalHindiQuery)
          catch:
              translatedQuery = originalHindiQuery  // fallback
      else:
          // Normal Hindi Enter/button search
          translatedQuery = translate(query)
          if empty → fallback to query
  else:
      translatedQuery = query

  originalQuery = originalHindiQuery OR query
  showTranslationInfo(originalQuery, translatedQuery, isNonEnglish, selectedTitle)

  // Step 2: Route queries
  searchTranslatedQuery = translatedQuery  (English)
  searchOriginalQuery = originalQuery      (Hindi)

  if selectedTitle exists:
      if selectedTitle is English:
          searchTranslatedQuery = selectedTitle  // full English title
      else:
          searchOriginalQuery = selectedTitle    // full Hindi title

  synonyms = isNonEnglish ? expandQuery(searchOriginalQuery) : null

  // Step 3: Execute search

  // ── PATH A: Suggestion click (clickedResourceId exists) ──
  if clickedResourceId:
      data = searchSolr(query, start=0, exact=true, resourceId=clickedResourceId)
      // Single panel, no tabs
      display single panel with "Selected Title" tag
      RETURN

  // ── PATH B: Normal search (Enter/button) ──
  translatedData = searchSolr(searchTranslatedQuery, exact=useExact)
  originalData = isNonEnglish ? searchSolr(searchOriginalQuery, synonyms, exact=useExact) : null

  // Step 4: Display results
  if both empty → show "No documents found"

  if isNonEnglish:
      show tabs: "Translated Results (N)" | "Original (Hindi) Results (N)"
  else:
      hide tabs (single panel)

  // Choose default tab
  if Hindi suggestion was clicked AND original panel has results:
      show Original tab
  elif translated panel has results:
      show Translated tab
  else:
      show Original tab
```

### Translation Info Banner

Three modes:
1. **Suggestion click**: Shows only `"Selected title: <title>"`
2. **Hindi Enter search**: Shows `"Original (Hindi): <hindi>" + "Translated (English): <english>"`
3. **English search**: Shows `"Query: <text>"`

---

## 8. Translation Service

### Model
- **IndicTrans2** by AI4Bharat
- Model: `ai4bharat/indictrans2-indic-en-dist-200M` (200M params, ~913MB download)
- Runs **offline** — no API calls after initial download
- Supports 10 Indic languages → English

### Inference Pipeline
```
1. Preprocess with IndicProcessor (adds language tags, normalizes)
2. Tokenize with AutoTokenizer (padding, truncation, max_length=256)
3. Generate with beam search (num_beams=5, max_length=256)
4. Decode tokens back to text
5. Postprocess with IndicProcessor (removes language tags)
```

### Client-Side Timeout (CRITICAL)
```
timeout = 5000ms (configurable)
Implementation: AbortController with setTimeout

1. Create new AbortController
2. Set timeout to abort after 5s
3. If parent signal also exists, chain abort
4. Pass controller.signal to fetch()
5. On timeout → controller.abort() → fetch throws AbortError
6. Always clearTimeout on success or error
```

**Why needed:** The translation model can hang indefinitely on certain inputs or under load. Without timeout, the entire UI blocks forever.

### Server-Side Details
- **Device selection**: MPS (Apple Silicon) > CUDA (NVIDIA) > CPU
- **MUST use float32** (not float16) for MPS compatibility — float16 causes NaN outputs
- **Warmup**: First inference after model load is slow; run a dummy translation at startup
- **Character limit**: 30 characters max (server-enforced, returns 400)
- **Usage tracking**: SQLite database logs every request (IP, query, timing, status)

### Production Deployment
- **macOS dev**: Use `waitress` (thread-based, no fork — MPS safe)
- **Linux prod**: Use `gunicorn` with `--workers 2 --timeout 120 --preload`
- Gunicorn `fork()` crashes MPS on macOS — never use gunicorn on Mac with MPS

---

## 9. Synonym Expansion

### Dictionary Format
```json
{
  "वाराणसी": ["वाराणसी", "काशी", "बनारस", "बेनारस"],
  "काशी": ["वाराणसी", "काशी", "बनारस", "बेनारस"]
}
```

**Bidirectional:** Every member of a synonym group is also a key. Looking up any variant returns all variants in the group.

### Usage in Search
1. Called only for non-English (Hindi) queries
2. Sends the Hindi query to `/expand` endpoint
3. If synonyms found (array.length > 1), builds Solr OR query:
   ```
   dc.title:("वाराणसी" OR "काशी" OR "बनारस" OR "बेनारस")
   ```
4. If no synonyms or error, falls back to exact phrase query

### Categories in Dictionary (449 entries)
- City name variants (Varanasi/Kashi/Banaras)
- Historical name changes (Mumbai/Bombay, Chennai/Madras)
- Leader name variants (Gandhi/Gandhiji/Mahatma)
- Institution name variants
- Freedom movement terms

---

## 10. UI Components & Layout

### Page Structure (top to bottom)
1. **Navbar** — logo + HOME/EXPLORE links
2. **Update Bar** — "Last Updated: X records on DD MMM YYYY" (fetched from Solr `*:*` count)
3. **Hero Section** — background image + search input + search button
4. **Suggestion Dropdown** — appears below search card
5. **Character Counter** — "N/30 characters" (visible only when typing Hindi)
6. **Results Area**:
   - Error Banner (red, hidden by default)
   - Translation Info Banner (shows query/translation details)
   - Loading Spinner ("Translating & searching...")
   - Tab Buttons (Translated Results | Original Hindi Results)
   - Panel: Translated Results (result cards + show more)
   - Panel: Original Results (result cards + show more)
   - No Results message

### Result Card Format
```
[#] Title (clickable link to Abhilekh Patal)
    [Identifier: PR_000001673540] [Year: 1957] [File: Prog., Nos. 21-48] [Branch: Home]
```

Each card links to: `https://abhilekh-patal.in/Category/ItemDetails/ItemDetails?itemId=<resourceId>`

### Tab Behavior
- **English search**: No tabs shown (single panel)
- **Hindi Enter/button search**: Two tabs shown
  - "Translated Results (N)" — searches English translation
  - "Original (Hindi) Results (N)" — searches original Hindi text
- **Suggestion click (any language)**: No tabs shown, single panel with "Selected Title" tag

### Character Counter Behavior
- Hidden when typing English (no char limit for English)
- Visible when typing Hindi (Devanagari detected)
- Normal: white text
- Warning (≥ 27 chars): yellow text
- Limit (= 30 chars): red bold text
- Input has `maxlength=30` attribute set when Hindi

---

## 11. Pagination (Show More)

### Strategy: Buffered Pagination
- Solr returns documents in batches of 100 (`solrBatchSize`)
- UI shows 10 at a time (`pageSize`)
- "Show More" button renders next 10 from buffer
- When buffer runs low (visible + pageSize > buffer), fetches next 100 from Solr

### Per-Panel State
Each panel (translated/original) independently tracks:
```
{
  query: string,        // Solr query for this panel
  synonyms: array|null, // For original panel synonym expansion
  allResults: array,    // Buffered Solr docs
  totalFound: number,   // Total from Solr numFound
  visibleCount: number, // Currently rendered count
  solrStart: number,    // Next Solr start offset
  isFetching: boolean   // Lock to prevent concurrent fetches
}
```

### Show More Logic
```
showMore(panelKey):
  // Fetch more from Solr if buffer is running low
  if visibleCount + pageSize > allResults.length AND solrStart < totalFound:
      if isFetching → return (prevent concurrent)
      isFetching = true
      newDocs = searchSolr(query, start=solrStart, synonyms)
      allResults.concat(newDocs)
      solrStart += newDocs.length
      if newDocs.length < solrBatchSize → solrStart = totalFound (no more)
      isFetching = false

  // Render next batch
  nextBatch = allResults[visibleCount : visibleCount + pageSize]
  render each doc as result card
  visibleCount += nextBatch.length
  updateShowMoreButton()
```

### Show More Button States
- "Show More" button visible when `remaining > 0`
- Counter text: "Showing X of Y results"
- When all shown: hide button, show "Showing all Y results"
- During fetch: button text changes to "Loading...", disabled

---

## 12. Edge Cases & Bug Fixes

### Edge Case 1: Translation Service Hangs
**Problem:** IndicTrans2 model can hang indefinitely on certain inputs.
**Solution:** Client-side 5-second timeout with AbortController.
**Behavior:** If translation times out:
- Suggestions: Hindi suggestions still appear (fired in parallel before translation)
- Search: Falls back to searching original Hindi query without English translation

### Edge Case 2: Empty Translation Result
**Problem:** Translation API returns success but `translated` is empty string or whitespace.
**Solution:** Check `!translatedVal || !translatedVal.trim()` and fallback to original query.

### Edge Case 3: Suggestion Click with Stop Words in Title
**Problem:** Titles like "History of the war." contain stop words. Searching `dc.title:"History of the war."` via text match returns wrong count or 0.
**Solution:** When a suggestion is clicked, search by `search.resourceid:<UUID>` instead of by title text. This always returns exactly 1 document.

### Edge Case 4: Hindi Suggestion Click Shows English in Hindi Tab
**Problem:** When Hindi user clicks English suggestion, both tabs searched by same resourceId, showing English document in Hindi tab.
**Solution:** Suggestion clicks bypass the dual-tab system entirely — show single panel with no tabs.

### Edge Case 5: Stale Suggestions After Fast Typing
**Problem:** User types fast, old suggestion responses arrive after newer ones.
**Solution:**
1. AbortController cancels previous fetch on each keystroke
2. Stale check: `if ($input.value.trim() !== val) return` before rendering

### Edge Case 6: Enter Key with Active Suggestion
**Problem:** Pressing Enter while a suggestion is keyboard-highlighted should select the suggestion, not trigger a search.
**Solution:** Check if suggestion dropdown is visible AND has an active (highlighted) item. If yes, let the suggestion keydown handler handle it; don't trigger `performSearch()`.

### Edge Case 7: Solr Special Characters in Fuzzy Search
**Problem:** User input may contain Solr special characters (`+`, `-`, `!`, `(`, `)`, etc.) that break fuzzy queries.
**Solution:** `sanitizeForFuzzy()` strips all non-alpha characters, removes words shorter than 2 chars, and removes stop words before building fuzzy query.

### Edge Case 8: Hindi Input → Clicked English Suggestion → Language Context Lost
**Problem:** User types Hindi "गांधी", sees English suggestion "Gandhi Memorial", clicks it. Input now shows English text. Language detection would say "English", losing the Hindi context.
**Solution:** Before overwriting input, store `suggestedFromQuery` (the original Hindi text). In `performSearch()`, if `suggestedFromQuery` is Hindi, force `currentLanguage = Hindi` regardless of current input text.

### Edge Case 9: Fuzzy Suggestions for Typos
**Problem:** User misspells "mehta" as "mhta", gets 0 prefix matches.
**Solution:** 2-phase suggestion lookup. Phase 1 tries prefix. If 0 results and input ≥ 3 chars, Phase 2 uses eDisMax fuzzy `~1` matching. Fuzzy results get distinct styling.

### Edge Case 10: MPS (Apple Silicon) Threading Crashes
**Problem:** Flask `threaded=True` with PyTorch MPS causes thread deadlocks.
**Solution (dev):** Use `waitress` (thread-based WSGI server, no forking, MPS-safe).
**Solution (prod):** Use `gunicorn` on Linux (no MPS, CPU-only, fork is safe).
**Never use gunicorn on macOS with MPS** — `fork()` crashes MPS initialization.

### Edge Case 11: Multi-word English Stop Word Removal for Display
**Problem:** Query tag shows `title:"History of the war"` but actual Solr query removes stop words for fuzzy matching.
**Solution:** Display tag uses `removeStopWords()` for multi-word English queries to show what Solr actually searched.

### Edge Case 12: Synonym OR Query for "Show More" Pagination
**Problem:** Original panel uses synonym OR query for initial search, but "Show More" needs to use the same query.
**Solution:** Store `synonyms` array in panel state. `showMore()` passes it to `searchSolr()` which rebuilds the same OR query.

---

## 13. Configuration Reference

### Frontend Config
```javascript
{
    translationServiceUrl: '/translate',     // Translation API endpoint
    solrUrl: '/solr/search/select',          // Solr select endpoint
    itemBaseUrl: 'https://abhilekh-patal.in/Category/ItemDetails/ItemDetails', // Document link base
    pageSize: 10,                            // Results shown per "Show More" click
    solrBatchSize: 100,                      // Docs fetched per Solr request (buffer)
    maxQueryLength: 30,                      // Max Hindi input chars (no limit for English)
    suggestMinChars: 2,                      // Min chars before autocomplete fires
    suggestMaxResults: 10,                   // Max suggestions shown
    suggestDebounceMs: 600,                  // Debounce delay for autocomplete
    translateTimeoutMs: 5000                 // Translation API timeout (ms)
}
```

### Backend Config
```python
MAX_QUERY_LENGTH = 30                        # Server-enforced char limit
MODEL_NAME = "ai4bharat/indictrans2-indic-en-dist-200M"  # HuggingFace model
PORT = 5002                                  # Translation service port
```

### Stop Words List (English)
```
the, a, an, of, in, on, at, to, for, and, or, is, was, are, were,
be, been, by, with, from, as, it, its, that, this, not, but, no
```

---

## 14. Data Structures

### Suggestion Item
```
{
  title: string,       // Full document title from Solr
  resourceId: string,  // Solr UUID (search.resourceid)
  fuzzy: boolean       // true if from Phase 2 fuzzy fallback
}
```

### Panel State
```
{
  query: string,           // Solr query string used for this panel
  synonyms: string[]|null, // Hindi synonyms for OR expansion
  allResults: SolrDoc[],   // Buffered documents from Solr
  totalFound: number,      // Total matches (Solr numFound)
  visibleCount: number,    // Currently rendered in DOM
  solrStart: number,       // Next Solr `start` offset
  isFetching: boolean      // Fetch lock
}
```

### Solr Document
```
{
  "dc.title": string|string[],              // Document title (may be array)
  "search.resourceid": string|string[],     // UUID
  "dc.identifier": string,                  // Archive ID
  "dc.date.issued": string,                 // "1957"
  "dc.identifier.fileName": string,         // File reference
  "dc.subject.branch": string               // Archive branch
}
```

Note: Solr may return multivalued fields as arrays. Always extract first element:
```
value = Array.isArray(field) ? field[0] : field
```

### Translation Response
```
{
  success: boolean,
  original: string,
  translated: string,
  src_lang: string,
  tgt_lang: string,
  processing_time_ms: number
}
```

### Synonym Response
```
{
  success: boolean,
  original: string,
  synonyms: string[],
  has_synonyms: boolean
}
```

---

## Appendix: Replication Checklist

When rebuilding in another language/framework, verify these behaviors:

- [ ] Hindi detection works (Devanagari regex U+0900-U+097F)
- [ ] Char counter shows only for Hindi input
- [ ] Autocomplete debounces at 600ms
- [ ] Previous autocomplete request is cancelled on new keystroke
- [ ] Hindi suggestions fire immediately (not blocked by translation)
- [ ] Translation has 5s timeout with graceful fallback
- [ ] Suggestions merge Hindi-first, deduplicated by lowercase title
- [ ] Fuzzy fallback fires when prefix returns 0 results and input ≥ 3 chars
- [ ] Clicking suggestion stores resourceId AND original query context
- [ ] Suggestion click → single panel, no tabs, search by resourceId
- [ ] Enter/button search → dual panels for Hindi, single panel for English
- [ ] Synonyms expand Hindi query into OR query
- [ ] Multi-word English uses fuzzy AND with stop-word removal
- [ ] Solr special chars sanitized before fuzzy query
- [ ] Show More pagination buffers 100, shows 10 at a time
- [ ] Both panels paginate independently
- [ ] Empty translation falls back to original query
- [ ] Translation error falls back to Hindi-only search
- [ ] Enter with active suggestion selects suggestion (not search)
- [ ] Click outside closes suggestion dropdown
