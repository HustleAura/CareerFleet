import re


ROLE_POLICY = "software_engineering_v1"
SOFTWARE_ROLE = re.compile(
    r"\b(?:sde|swe)(?:\d+|i{1,3}|iv)?\b|"
    r"\bsoftware[\s-]+(?:(?:development|dev)[\s-]+)?engineer\b|"
    r"\b(?:back[\s-]*end|front[\s-]*end|full[\s-]*stack)[\s-]+engineer\b", re.I)
EXCLUDED_ROLE = re.compile(
    r"\b(?:sre|dev[\s-]*ops|devsecops|mlops|sde[\s-]*t|qa|qe|"
    r"site[\s-]+reliability|quality[\s-]+(?:assurance|engineer(?:ing)?)|"
    r"test(?:ing|er)?|scientist|analyst|manager|director|recruiter)\b|"
    r"\b(?:hardware|support|operations|sales)[\s-]+(?:software[\s-]+)?engineer\b|"
    r"\b(?:application|integration|production|technical)[\s-]+support\s*(?=$|[,)/])|"
    r"\b(?:engineering|people|product|program|project)[\s-]+management\b|"
    r"\b(?:head[\s-]+of|vice[\s-]+president|vp)\b", re.I)
EXCLUDED_SPECIALIZATION = re.compile(
    r"(?:^|[,(/-])\s*(?:management|sales|operations|hardware|support|quality)"
    r"(?:[\s-]+only)?\s*(?=$|[,)/])", re.I)
AMBIGUOUS_ROLE = re.compile(
    r"\b(?:data|platform|cloud|security|network|systems?|machine[\s-]+learning|ai)"
    r"[\s-]+engineer\b", re.I)
SDE_TWO = re.compile(r"\b(?:sde|software\s+(?:(?:development|dev)\s+)?engineer)\s*[-,:]?\s*(?:ii|2)\b", re.I)
OTHER_LEVEL = re.compile(r"\b(?:sde|software\s+(?:(?:development|dev)\s+)?engineer)\s*[-,:]?\s*(?:iii|iv|i|1|3|4)\b", re.I)
OTHER_AMAZON_FAMILY = re.compile(r"\b(?:principal|staff)\b", re.I)


def validate_role_policy(policy):
    if policy != ROLE_POLICY:
        raise ValueError(f"role_filter must be {ROLE_POLICY}")
    return policy


def normalized_title(title):
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Role filtering requires a nonempty title")
    return title.replace("\u2013", "-").replace("\u2014", "-").replace("\u2011", "-")


def software_role_filter(title):
    title = normalized_title(title)
    # Domain/team names such as "Inventory Management" are not management roles.
    if EXCLUDED_ROLE.search(title) or EXCLUDED_SPECIALIZATION.search(title):
        return "excluded"
    if SOFTWARE_ROLE.search(title) and not AMBIGUOUS_ROLE.search(title):
        return "matched"
    if re.search(r"\b(?:engineer|developer)\b", title, re.I):
        return "unresolved"
    return "excluded"


def amazon_title_filter(title):
    title = normalized_title(title)
    role = software_role_filter(title)
    if role != "matched":
        return role
    if not SDE_TWO.search(title) or OTHER_AMAZON_FAMILY.search(title):
        return "excluded"
    if OTHER_LEVEL.search(title) or re.search(r"\b(?:ii|2)\s*/\s*(?:iii|3)\b", title, re.I):
        return "unresolved"
    return "matched"


def classify_title(company, title, policy=ROLE_POLICY):
    validate_role_policy(policy)
    role = software_role_filter(title)
    return {"role_filter": role,
            "title_filter": amazon_title_filter(title) if company == "amazon" else role}
