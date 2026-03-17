import os
import json
from google.cloud import vision, storage
from google.oauth2 import service_account

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(BASE_DIR, "service-account.json")


def get_credentials():
    if not os.path.exists(CREDENTIALS_PATH):
        raise FileNotFoundError(
            f"No se encontró el archivo de credenciales: {CREDENTIALS_PATH}"
        )

    return service_account.Credentials.from_service_account_file(CREDENTIALS_PATH)


def get_vision_client():
    credentials = get_credentials()
    return vision.ImageAnnotatorClient(credentials=credentials)


def get_storage_client():
    credentials = get_credentials()
    return storage.Client(credentials=credentials)


def upload_file_to_gcs(bucket_name: str, source_file_path: str, destination_blob_name: str) -> str:
    if not os.path.exists(source_file_path):
        raise FileNotFoundError(f"No se encontró el archivo PDF: {source_file_path}")

    storage_client = get_storage_client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file_path)

    return f"gs://{bucket_name}/{destination_blob_name}"


def extract_text_from_pdf(pdf_path: str, bucket_name: str, cleanup: bool = False) -> str:
    """
    Extrae texto de un PDF usando Google Cloud Vision + Cloud Storage.

    Args:
        pdf_path: ruta local del PDF
        bucket_name: nombre del bucket en GCS
        cleanup: si True, elimina archivos temporales del bucket al final

    Returns:
        Texto OCR completo del PDF
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"No se encontró el archivo PDF: {pdf_path}")

    vision_client = get_vision_client()
    storage_client = get_storage_client()

    pdf_name = os.path.basename(pdf_path)
    pdf_name_no_ext = os.path.splitext(pdf_name)[0]

    input_blob_name = f"input/{pdf_name}"
    output_prefix = f"output/{pdf_name_no_ext}/"

    gcs_source_uri = upload_file_to_gcs(bucket_name, pdf_path, input_blob_name)
    gcs_destination_uri = f"gs://{bucket_name}/{output_prefix}"

    feature = vision.Feature(type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION)

    input_config = vision.InputConfig(
        gcs_source=vision.GcsSource(uri=gcs_source_uri),
        mime_type="application/pdf",
    )

    output_config = vision.OutputConfig(
        gcs_destination=vision.GcsDestination(uri=gcs_destination_uri),
        batch_size=5,
    )

    request = vision.AsyncAnnotateFileRequest(
        features=[feature],
        input_config=input_config,
        output_config=output_config,
    )

    operation = vision_client.async_batch_annotate_files(requests=[request])
    operation.result(timeout=600)

    bucket = storage_client.bucket(bucket_name)
    blobs = list(bucket.list_blobs(prefix=output_prefix))

    extracted_text_parts = []

    for blob in blobs:
        if not blob.name.endswith(".json"):
            continue

        content = blob.download_as_text(encoding="utf-8")
        data = json.loads(content)

        for response in data.get("responses", []):
            text = response.get("fullTextAnnotation", {}).get("text", "")
            if text:
                extracted_text_parts.append(text)

    full_text = "\n".join(extracted_text_parts).strip()

    if cleanup:
        # Borra JSON de salida
        for blob in blobs:
            blob.delete()

        # Borra PDF de entrada
        input_blob = bucket.blob(input_blob_name)
        if input_blob.exists():
            input_blob.delete()

    return full_text


if __name__ == "__main__":
    BUCKET_NAME = "PON_AQUI_TU_BUCKET"
    test_pdf = os.path.join(BASE_DIR, "test.pdf")

    try:
        text = extract_text_from_pdf(test_pdf, BUCKET_NAME, cleanup=False)

        print("\nTEXTO DETECTADO DEL PDF:\n")
        print(text[:5000] if text else "No se detectó texto.")

    except Exception as e:
        print(f"Error: {e}")