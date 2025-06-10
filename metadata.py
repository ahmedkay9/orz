import logging
from thefuzz import process as fuzzy_process
from config import API_KEY, CONFIDENCE_THRESHOLD

# Use a singleton pattern to ensure we only initialize the TVDB API client once.
TVDB_API = None
def get_tvdb_instance():
    """
    Initializes and returns a single, shared instance of the TVDB API client.

    Returns:
        tvdb_v4_official.TVDB: The initialized TVDB API client instance.
    """
    global TVDB_API
    if TVDB_API is None:
        if not API_KEY:
            raise EnvironmentError("TVDB_API_KEY not found in environment variables.")
        import tvdb_v4_official
        TVDB_API = tvdb_v4_official.TVDB(API_KEY)
    return TVDB_API

def search_tvdb_metadata(parsed_info, media_type=None):
    """
    Searches TheTVDB for metadata, checking English translations for better matching.

    Args:
        parsed_info (dict): The output from the parse_filename function.
        media_type (str, optional): A hint ('series' or 'movie') to filter results.

    Returns:
        dict or None: The verified metadata from TVDB, or None if no confident match is found.
    """
    query = parsed_info["title"]
    if not query: return None
    try:
        tvdb = get_tvdb_instance()
        search_results = tvdb.search(query=query, year=parsed_info.get("year"), limit=10)

        if not search_results:
            logging.warning(f"No TVDB results found for query: '{query}'")
            return None

        if media_type:
            search_results = [r for r in search_results if r.get('type') == media_type]
        if not search_results:
            logging.warning(f"Found results for '{query}', but none matched required type '{media_type}'.")
            return None

        choices = {}
        for result in search_results:
            if result.get('name'):
                choices[result['name']] = result
            if (result.get('translations', {}).get('eng') and
                    result['translations']['eng'] != result.get('name')):
                choices[result['translations']['eng']] = result

        if not choices:
            logging.warning(f"No usable names found in search results for '{query}'.")
            return None

        best_match_name, confidence = fuzzy_process.extractOne(query, choices.keys())

        if confidence >= CONFIDENCE_THRESHOLD:
            selected_result = choices[best_match_name]
            if selected_result.get('translations', {}).get('eng'):
                selected_result['name'] = selected_result['translations']['eng']

            logging.info(f"Confident match for '{query}': '{selected_result['name']}' (Matched on: '{best_match_name}', Confidence: {confidence}%).")
            return selected_result
        else:
            logging.warning(f"Low confidence for '{query}': Best guess '{best_match_name}' ({confidence}%) is below threshold.")
            return None
    except Exception as e:
        logging.error(f"Error during TVDB search: {e}", exc_info=True)
        return None
