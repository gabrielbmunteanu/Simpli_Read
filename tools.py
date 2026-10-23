import base64
import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel,Field, ValidationError, computed_field
import json
from pathlib import Path

import uuid
import re


load_dotenv()

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
MODEL = "gemini-flash-lite-latest"
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

BOOKS = Path(__file__).parent / "books.json"


# ---------------------------------------------------------------- something
def file_item(path, resolution=None):
    # An image or a PDF as one item of the input list. The extension decides which.
    path = Path(path)
    mime = MIME[path.suffix.lower()]
    item = {
        "type": "image",
        "data": base64.b64encode(path.read_bytes()).decode(),
        "mime_type": mime,
    }
    if resolution:
        item["resolution"] = resolution
    return item
# ---------------------------------------------------------------- data

def write(data):
    if not BOOKS.exists():
        BOOKS.write_text(json.dumps(data, indent=4), encoding="utf-8")
    else:
        with open("books.json", "r+") as file:
            new_books = data["books"]
            books = json.load(file)  

            existing_ids = {b["id"] for b in books.get("books", []) if "id" in b}
            books_to_add = [b for b in new_books if b.get("id") not in existing_ids]            
                       
            if books_to_add:
                books["books"].extend(books_to_add)
                file.seek(0)
                file.truncate()
                json.dump(books, file, indent=4)
 


# ---------------------------------------------------------------- schemas/arguments

class Author(BaseModel):
    author : str = Field(description = "The author or one of the authors of the book") 

class Genre(BaseModel):
    genre : str = Field(description = "The genre or one of the genres of the book")

class Book(BaseModel):
    authors : list[Author] 
    title : str  = Field(description = "Title of the book as it is in the photo") 
    english_title: str = Field(description = "Title of the book in english") 
    genres : list[Genre] 

    @computed_field
    @property
    def id(self) -> str:
        clean_title = re.sub(r"\s+", " ", self.english_title.strip().lower())
        clean_authors = sorted(
            re.sub(r"\s+", " ", a.author.strip().lower())
            for a in self.authors if a.author.strip()
        )
        authors_str = "; ".join(clean_authors) if clean_authors else "unknown"
        seed = f"{clean_title}::{authors_str}"
        return str(uuid.uuid5(uuid.NAMESPACE_OID, seed))

class Shelf(BaseModel):
    books : list[Book]

# ---------------------------------------------------------------- tools

def add_books_to_memory(reply):
    write(reply.model_dump())

# name: (argument model, function, description). The declarations are built from it.
TOOLS = {"add_books_to_memory" : (Shelf,add_books_to_memory,"Scans a photo of a bookshelf and extracts information from all the books and stores it"),}

ASK_FIRST = {}#{"add_books_to_memory"}

DECLARATIONS = [
    {"type": "function", "name": name, "description": description, "parameters": model.model_json_schema(mode="validation")}
    for name, (model, _, description) in TOOLS.items()
]


def run_tool(name, arguments, confirm):  #The True value in run tool is just a placeholder there will be a function that asks users to confirm actions
    """Run one call the model asked for. Every failure comes back as a result; nothing raises."""
    if name not in TOOLS:
        return {"error": f"There is no tool called {name}. The tools are: {', '.join(TOOLS)}."}
    model, function, _ = TOOLS[name]
    try:
        args = model.model_validate(arguments)
    except ValidationError as error:
        problem = error.errors()[0]
        field = ".".join(str(part) for part in problem["loc"]) or "arguments"
        return {"error": f"Invalid {field}: {problem['msg']}. Fix it and call again."}
    try:
        result = function(args, confirm) if name in ASK_FIRST else function(args)
    except Exception as error:
        # A write that failed half-way may or may not have changed the data. Say
        # so, or the agent will repeat it blindly and write it twice.
        return {"error": f"{name} failed: {str(error).rstrip('.')}. If it writes, it may or may not "
                         "have changed the data: read the data again before repeating it."}
    # The API takes a dict of JSON values: wrap anything else, and turn dates into text.
    if not isinstance(result, dict):
        result = {"result": result}
    return json.loads(json.dumps(result, default=str))

# ---------------------------------------------------------------- this is not a tool its just to test if the tools are working fine

def confirm():
    """
    This is a place holder function for testing purposes
    it will be modified to ask users for permission in later stages of the project
    """
    return True

def run_agent(path = None,question = None):

    if path:
            input=[file_item(path), {"type": "text", "text": question}]
    else:
        input = question

    interaction = client.interactions.create(
        model = MODEL,
        input=input,
        system_instruction="You are an intelligent multimodal visual assistant for a book discovery and reading companion app. "
                        "Your core capability is inspecting images uploaded by users (such as bookshelves, book covers, specific book pages, receipts, or reading spots) alongside an optional user query, determining the user's intent, and routing the request to the appropriate tool function.",
        tools = DECLARATIONS

    )

    print(interaction.steps)

    for step in interaction.steps or []:
        if step.type == "function_call":
            print("call:       ", step.name, "  id:", step.id)

            run_tool(step.name,step.arguments,confirm)
    print("output_text:", repr(interaction.output_text))

print(run_agent("estante_casa.jpg","what are the books present in this photo?"))