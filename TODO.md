- [x] Fix universal crawler company URL/alias mapping for: tca, kpmg, jpmorgan, wipro

- [ ] Remove incorrect empty alias entries and improve careers discovery for those companies
- [ ] Ensure allowlist logic permits official/ATS domains for these companies
- [ ] Update companies_supported.txt to include: tca, kpmg, jpmorgan, wipro
- [ ] Add/adjust tests to prevent regressions (discovery + non-empty jobs with mocked/fallback)
- [ ] Run pytest and verify /jobs/{company} returns total > 0 for each company

