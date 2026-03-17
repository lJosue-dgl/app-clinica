import re


def _extract_value(text: str, pattern: str):
    match = re.search(pattern, text, re.IGNORECASE)

    if not match:
        return None

    value = match.group(1).replace(",", ".")

    try:
        return float(value)
    except:
        return None


def parse_lab_results(text: str):

    results = {
        "glucose": None,
        "hba1c": None,
        "triglycerides": None,
        "hdl": None,
        "ldl": None,
        "alt_tgp": None,
        "ast_tgo": None,
    }

    patterns = {
        "glucose": r"\b(?:Glucosa|Glucose)\b[^0-9]*([0-9]+(?:[.,][0-9]+)?)",

        "hba1c": r"(?:HbA1c|A1c|Hemoglobina\s+glicosilada)[^0-9]*([0-9]+(?:[.,][0-9]+)?)",

        "triglycerides": r"(?:Triglic[eé]ridos|Triglycerides)[^0-9]*([0-9]+(?:[.,][0-9]+)?)",

        "hdl": r"\bHDL\b[^0-9]*([0-9]+(?:[.,][0-9]+)?)",

        "ldl": r"\bLDL\b[^0-9]*([0-9]+(?:[.,][0-9]+)?)",

        "alt_tgp": r"\b(?:ALT|TGP)\b[^0-9]*([0-9]+(?:[.,][0-9]+)?)",

        "ast_tgo": r"\b(?:AST|TGO)\b[^0-9]*([0-9]+(?:[.,][0-9]+)?)",
    }

    for key, pattern in patterns.items():
        results[key] = _extract_value(text, pattern)

    return results


if __name__ == "__main__":

    sample_text = """
    Glucosa 105
    HbA1c 5.7
    Triglicéridos 180
    HDL 45
    LDL 120
    TGP 35
    TGO 28
    """

    results = parse_lab_results(sample_text)

    print("\nRESULTADOS EXTRAIDOS:\n")
    print(results)