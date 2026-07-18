import re
from typing import Any


def parse_job_details(title: str) -> dict[str, Any]:
    lowered = title.lower()

    role = "Software Engineer"
    if "frontend" in lowered or "ui" in lowered:
        role = "Frontend Engineer"
    elif "backend" in lowered or "platform" in lowered:
        role = "Backend Engineer"
    elif "data" in lowered:
        role = "Data Engineer"
    elif "ml" in lowered or "machine learning" in lowered:
        role = "Machine Learning Engineer"

    skills: list[str] = []
    if "python" in lowered:
        skills.append("Python")
    if "aws" in lowered:
        skills.append("AWS")
    if "docker" in lowered:
        skills.append("Docker")
    if "kubernetes" in lowered:
        skills.append("Kubernetes")
    if not skills:
        skills = ["Software Engineering"]

    experience = "2-4 years"
    if re.search(r"\b(sr|senior|principal)\b", lowered):
        experience = "4-7 years"
    elif re.search(r"\b(ii|iii|lead)\b", lowered):
        experience = "3-5 years"

    category = "Software Engineering"
    if "data" in lowered:
        category = "Data Engineering"
    elif "ml" in lowered or "machine learning" in lowered:
        category = "Machine Learning"

    return {
        "role": role,
        "skills": skills,
        "experience": experience,
        "category": category,
    }
