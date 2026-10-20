import base64
import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel



load_dotenv()

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
MODEL = "gemini-flash-lite-latest"""
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

def file_item(path, resolution=None):
    # An image or a PDF as one item of the input list. The extension decides which.
    path = Path(path)
    mime = MIME[path.suffix.lower()]
    item = {
        "type": "document" if mime == "application/pdf" else "image",
        "data": base64.b64encode(path.read_bytes()).decode(),
        "mime_type": mime,
    }
    if resolution:
        item["resolution"] = resolution
    return item

class Book(BaseModel):
    author : str | None
    title : str | None
    english_title: str | None
    genre : str | None


class Shelf(BaseModel):
    books : list[Book]


def extract_books(path, resolution=None):
    # One call: the file, then the question. With a schema, the reply is validated into it.
    
    interaction = client.interactions.create(
        model=MODEL,
        input=[file_item(path, resolution), {"type": "text", "text": "What books are present in this image?"}],
        system_instruction="You scan images of bookshelves and extract the author, the title, the title but in english and fill in the genre"
                            "If you cannot find the author you should fill it in based on the title",
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": Shelf.model_json_schema()
        },
    )
    reply = Shelf.model_validate_json(interaction.output_text)
    return reply

extract_function = {
    "type" : "function",
    "name" : "extract",
    "description" : "Scans an photo of bookshelves and extracts informations from all the books",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["path"],
    },
}

shelf = extract_books("estante_casa.jpg")
for book in shelf.books:
    print(f"Title: {book.title}")
    print(f"English Title: {book.english_title}")
    print(f"Author: {book.author}")
    print(f"Genre: {book.genre}")
    print("") 




