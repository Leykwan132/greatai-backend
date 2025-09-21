https://greataihackathon.com/

# GreatAI Backend - Core

This repository contains the backend implementation for the GreatAI Hackathon. It is built using FastAPI to manage tool calls for AI agents.

## Features

- FastAPI-based API framework.
- Centralized tool call management for AI agents.
- Exclusion of sensitive files (`credentials.json`, `token.json`) from version control.

## Project Structure

```
credentials.json       # Sensitive credentials (ignored in .gitignore)
main.py                # FastAPI application entry point
pyproject.toml         # Project metadata and dependencies
README.md              # Project documentation
uv.lock                # Dependency lock file
__pycache__/           # Python cache files (ignored in .gitignore)
```

## Getting Started

### Prerequisites

- Python 3.10 or higher.
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```

### Running the Server

Start the FastAPI server:

```bash
uvicorn main:app --reload
```

Access the server at `http://127.0.0.1:8000`.

## Contributing

Fork the repository and submit pull requests for contributions.

## License

This project is licensed under the MIT License. Refer to the `LICENSE` file for details.

---

For more information, visit [GreatAI Hackathon](https://greataihackathon.com/).
