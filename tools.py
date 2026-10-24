import base64
import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel,Field, ValidationError, computed_field
import json
import builtins

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
        with open(BOOKS, "r+", encoding="utf-8") as file:
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

class NoArgs(BaseModel): 
    """
    A model for tools that don't take any arguments
    """
    pass

class BookTitle(BaseModel):
    title: str = Field(description="The exact title of the book to look up (either in its original language or in English)")

class DeleteBook(BaseModel):
    id: str = Field(description="The id of the book to delete, as returned by list_book_by_title or list_book_by_title_and_author")
 
class BookTitleAndAuthor(BaseModel):
    title: str = Field(description="The exact title of the book to look up (either in its original language or in English)") 
    author: str = Field(description="The exact author of the book confirmed by the user") 
 
# ---------------------------------------------------------------- tools 

def add_books_to_memory(reply):
    write(reply.model_dump())


def list_books(_=None):
    if not BOOKS.exists():
        return "No books found"
    try:
        with open(BOOKS, "r", encoding="utf-8") as file:
            books = json.load(file).get("books", [])
            return books if books else "No books found"
    except (json.JSONDecodeError, OSError):
        return "No books found" 


def list_book_by_title(args):
    # Support being passed a BookTitle object or a raw string
    target_title = (args.title if hasattr(args, "title") else str(args)).strip().lower()

    books = list_books()
    if isinstance(books, str):
        return books  # Returns "No books found" if the file is empty/missing

    # Exact match against either original title or english title
    matching_books = [
        book for book in books
        if book.get("title", "").strip().lower() == target_title
        or book.get("english_title", "").strip().lower() == target_title
    ]

    if not matching_books:
        return f"Book '{target_title}' was not found in the library." 

    # Return the book (including its 'id'). If duplicate titles exist, return all matches so the user/AI can inspect IDs.
    if len(matching_books) == 1:
        return matching_books[0] 
    else:   
        return { 
                "status": "ambiguous",
                "title" : target_title, 
                "message": "Multiple books found with this title. You must call 'list_book_by_title_and_author' with the author to obtain the ID. You must ask the user for the correct author."
        }

    
def list_book_by_title_and_author(args):
    target_title = (args.title if hasattr(args, "title") else str(args.get("title", ""))).strip().lower()
    target_author = (args.author if hasattr(args, "author") else str(args.get("author", ""))).strip().lower()

    books = list_books()
    if isinstance(books, str):
        return books

    for book in books:
        title_match = target_title in (book.get("title", "").strip().lower(), book.get("english_title", "").strip().lower())
        author_match = any(a.get("author", "").strip().lower() == target_author for a in book.get("authors", []))
        
        if title_match and author_match:
            return book

    return f"Book '{target_title}' by '{target_author}' was not found in the library."


def delete_book(args):
    target_id = args.id if hasattr(args, "id") else str(args)

    if not BOOKS.exists():
        return "No books found"

    with open(BOOKS, "r+", encoding="utf-8") as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError:
            return "Library data is empty or corrupted"

        current_books = data.get("books", [])
        books_to_keep = [b for b in current_books if b.get("id") != target_id]

        # Check if any book was actually removed
        if len(books_to_keep) == len(current_books):
            return f"Book with id '{target_id}' was not found in the library."

        # Save the updated list (even if it's now empty: [])
        data["books"] = books_to_keep
        file.seek(0)
        file.truncate()
        json.dump(data, file, indent=4, ensure_ascii=False)

    return f"Book with id '{target_id}' successfully deleted."


 

# name: (argument model, function, description). The declarations are built from it.
TOOLS = {"add_books_to_memory" : (Shelf, add_books_to_memory, "Scans a photo of a bookshelf and extracts information from all the books and stores it"),
        "list_book_by_title" : (BookTitle, list_book_by_title, "Lists books by title"),
        "delete_book" : (DeleteBook, delete_book, "Deletes a book by id"),
        "list_book_by_title_and_author" : (BookTitleAndAuthor, list_book_by_title_and_author, "Lists books by title and author"),
        "list_books": (NoArgs, list_books, "Lists all books currently in memory"),
     }

ASK_FIRST = {}#{"add_books_to_memory"}

DECLARATIONS = [
    {"type": "function", "name": name, "description": description, "parameters": model.model_json_schema(mode="validation")}
    for name, (model, _, description) in TOOLS.items()
]

 
def run_tool(name, arguments, confirm=True):  #The True value in run tool is just a placeholder there will be a function that asks users to confirm actions
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


NOTES = ("(", "_", "{", "[", "thought", "No tool call", "is_call_allowed", "id=", "data:")

def unfinished(text):
    # Empty, very short, or opening like a working note rather than an answer.
    return len(text) < 12 or text.startswith(NOTES)

def run_agent(message, system, path = None, tools=DECLARATIONS, previous_id=None, max_rounds=8):
    """The model asks, your code acts, the result goes back: until the model stops asking."""
    if path:
        input=[file_item(path), {"type": "text", "text": message}]
    else:
        input = message
    send = dict(model=MODEL, system_instruction=system, tools=tools)  # on every request
    interaction = client.interactions.create(input=input, previous_interaction_id=previous_id, **send)
    rounds, nudged = 0, False
    while True:
        calls = [step for step in interaction.steps if step.type == "function_call"]
        if not calls:
            text = (interaction.output_text or "").strip()
            if unfinished(text) and not nudged:
                nudged = True
                interaction = client.interactions.create(
                    input="Answer the user's question in one or two sentences.",
                    previous_interaction_id=interaction.id, **send)
                continue
            print("reply:", "[no usable answer: the tool log is what was done]" if unfinished(text) else text)
            return interaction
        if rounds == max_rounds:
            print(f"reply: [stopped after {max_rounds} rounds: the tool log is what was done]")
            return interaction
        rounds += 1
        results = []
        for call in calls:  # one after another, in the order given
            result = run_tool(call.name, call.arguments)
        
            if isinstance(result, dict) and result.get("status") == "ambiguous":
                user_choice = builtins.input("Please specify the author of the book to delete: ").strip()     
                if user_choice:
                    result["user_selected_author"] = user_choice
                    result["message"] += f" The user clarified the author is '{user_choice}'" 

            print(f"  round {rounds}  {call.name} {json.dumps(call.arguments)} -> {json.dumps(result)[:90]}")
            results.append({"type": "function_result", "call_id": call.id, "name": call.name, "result": result})            
            
        interaction = client.interactions.create(input=results, previous_interaction_id=interaction.id, **send)



system_instr = "You are an intelligent multimodal visual assistant for a book discovery \
                and reading companion app. Your core capability is \
                inspecting images uploaded by users (such as bookshelves, book covers, specific book pages, receipts, \
                or reading spots) alongside an optional user query, determining the user's intent, \
                and routing the request to the appropriate tool function."

# print(run_agent(message="what are the books present in this photo?", system=system_instr, path="estante_casa.jpg"))

print(run_agent(message="Delete the book Persuasion", system=system_instr,path = None)) 
 









# def run_agent(path = None,question = None):

#     if path:
#             input=[file_item(path), {"type": "text", "text": question}]
#     else:
#         input = question

#     interaction = client.interactions.create(
#         model = MODEL,
#         input=input,
#         system_instruction="You are an intelligent multimodal visual assistant for a book discovery and reading companion app. "
#                         "Your core capability is inspecting images uploaded by users (such as bookshelves, book covers, specific book pages, receipts, or reading spots) alongside an optional user query, determining the user's intent, and routing the request to the appropriate tool function.",
#         tools = DECLARATIONS

#     )

#     print(interaction.steps)

#     for step in interaction.steps or []:
#         if step.type == "function_call":
#             print("call:       ", step.name, "  id:", step.id)

#             run_tool(step.name,step.arguments,confirm)
#     print("output_text:", repr(interaction.output_text))
 