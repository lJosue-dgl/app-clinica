import re
import os
from google.cloud import vision
from google.oauth2 import service_account

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(BASE_DIR, "service-account.json")


def get_vision_client():
    credentials = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH
    )
    return vision.ImageAnnotatorClient(credentials=credentials)


def extract_text_from_image(image_path):
    client = get_vision_client()

    with open(image_path, "rb") as f:
        content = f.read()

    image = vision.Image(content=content)
    response = client.document_text_detection(image=image)

    if response.error.message:
        raise Exception(response.error.message)

    return response.full_text_annotation.text or ""


def parse_lab_results(text):
    results = {
        "hemoglobin": None,
        "hematocrit": None,
        "glucose": None,
        "hba1c": None,
        "triglycerides": None,
        "hdl": None,
        "ldl": None,
        "alt_tgp": None,
        "ast_tgo": None,
    }

    patterns = {
        "hemoglobin": r"Hemoglobina[^0-9]*([0-9]+(?:[.,][0-9]+)?)",
        "hematocrit": r"Hematocrito[^0-9]*([0-9]+(?:[.,][0-9]+)?)",
        "glucose": r"(?:Glucosa|Glucose)[^0-9]*([0-9]+(?:[.,][0-9]+)?)",
        "hba1c": r"(?:HbA1c|A1c|Hemoglobina glicosilada)[^0-9]*([0-9]+(?:[.,][0-9]+)?)",
        "triglycerides": r"(?:Triglic[eé]ridos|Triglycerides)[^0-9]*([0-9]+(?:[.,][0-9]+)?)",
        "hdl": r"HDL[^0-9]*([0-9]+(?:[.,][0-9]+)?)",
        "ldl": r"LDL[^0-9]*([0-9]+(?:[.,][0-9]+)?)",
        "alt_tgp": r"(?:ALT|TGP)[^0-9]*([0-9]+(?:[.,][0-9]+)?)",
        "ast_tgo": r"(?:AST|TGO)[^0-9]*([0-9]+(?:[.,][0-9]+)?)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).replace(",", ".")
            results[key] = float(value)

    return results


if __name__ == "__main__":
    image_path = os.path.join(BASE_DIR, "test.png")
    text = extract_text_from_image(image_path)

    print("\nTEXTO DETECTADO:\n")
    print(text)

    parsed = parse_lab_results(text)

    print("\nVALORES EXTRAIDOS:\n")
    print(parsed)