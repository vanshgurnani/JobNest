- [x] Update API: add pagination params (e.g., page/limit) for /jobs and /jobs/{company}

- [x] Update crawler functions to accept pagination (page/limit) and apply offset/limit correctly

- [x] Fix location filtering for Meta + Microsoft: ensure location query is passed into their search payload/GraphQL variables and actually used

- [x] Update README to document pagination and location filtering behavior

- [x] Run tests (`pytest -q`) and basic smoke-check by calling API endpoints (added PYTHONPATH=. for tests)


