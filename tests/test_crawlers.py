from app.crawler.base import extract_jobs_from_html


def test_extract_jobs_from_html_prioritizes_job_links() -> None:
    html = """
    <html><body>
        <a href="/jobs/100">Software Engineer</a>
        <a href="/jobs/101">Data Scientist</a>
        <a href="/jobs/102">Marketing</a>
    </body></html>
    """

    jobs = extract_jobs_from_html(
        html,
        company="TestCo",
        base_url="https://example.com",
        location_hint="Seattle",
    )

    assert any(job["title"] == "Software Engineer" for job in jobs)
    assert jobs[0]["location"] == "Seattle"
