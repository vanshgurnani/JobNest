import asyncio
import json
import urllib.parse
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        search_results_call = {}
        
        async def handle_response(response):
            if "graphql" in response.url:
                request = response.request
                post_data = request.post_data or ""
                try:
                    res_json = await response.json()
                except Exception:
                    res_json = None
                
                parsed = urllib.parse.parse_qs(post_data)
                fname = parsed.get("fb_api_req_friendly_name", [""])[0]
                if fname == "CareersJobSearchResultsV2DataQuery":
                    search_results_call["post_data"] = parsed
                    search_results_call["response"] = res_json
                    print(f"Found CareersJobSearchResultsV2DataQuery!")
                    print(f"doc_id: {parsed.get('doc_id', ['?'])[0]}")
                    print(f"variables: {parsed.get('variables', ['?'])[0][:200]}")
                    print(f"response jobs count: {len(res_json.get('data', {}).get('job_search_with_featured_jobs_v2', {}).get('all_jobs', [])) if res_json and 'data' in res_json else 'N/A - error'}")
                    if res_json and 'errors' in res_json:
                        print("ERRORS:", res_json['errors'])
                    
        page.on("response", handle_response)
        
        print("Navigating to Meta Careers...")
        await page.goto("https://www.metacareers.com/jobs?q=software", wait_until="networkidle")
        await asyncio.sleep(5)
        
        with open("meta_latest.json", "w") as f:
            json.dump(search_results_call, f, indent=2)
            
        print("Done.")
        await browser.close()

asyncio.run(main())
