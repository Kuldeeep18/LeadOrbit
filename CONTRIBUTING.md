# Contributing to LeadOrbit

Thank you for your interest in contributing to LeadOrbit! 🚀

We welcome contributions of all sizes, including bug fixes, documentation improvements, feature enhancements, testing, and UI updates.

## Getting Started

### 1. Fork the Repository

Fork the repository to your GitHub account.

### 2. Clone Your Fork

```bash
git clone https://github.com/<your-username>/LeadOrbit.git
cd LeadOrbit
```

### 3. Create a Virtual Environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables

Create a `backend/.env` file and add the required environment variables as described in the README.

### 6. Run Database Migrations

```bash
python backend/manage.py migrate
```

### 7. Start the Backend

```bash
cd backend
python manage.py runserver 8000
```

### 8. Start the Frontend

Open a second terminal:

```bash
cd frontend
python -m http.server 8080
```

Visit:

```text
http://127.0.0.1:8080/login.html
```

---

## Branch Naming Convention

Please create a dedicated branch for every contribution.

Examples:

```text
feature/32-contributing-guide
fix/45-login-error
docs/20-readme-update
```

Avoid committing directly to the `main` branch.

---

## Commit Message Guidelines

This project follows Conventional Commits.

Examples:

```text
feat: add campaign filtering feature
fix: resolve authentication bug
docs: add contributing guide
refactor: improve API structure
test: add campaign unit tests
```

---

## Running Tests

Run backend tests before submitting a pull request.

```bash
cd backend
python manage.py test
```

Ensure all tests pass successfully.

---

## Privacy and Data Handling

Please do not commit real personal data, customer lists, credentials, or API keys to this repository.

Use only synthetic or clearly labeled placeholder values in examples, test fixtures, and sample files. CSV fixtures should live under tests/fixtures and contain synthetic values only.

If you need sample contact data for demos or tests, use placeholder addresses such as test-user-1@example.com and generic names instead of real individuals' information.

---

## Code Style Guidelines

### Python

* Follow PEP 8 standards
* Use meaningful variable and function names
* Keep functions small and maintainable
* Add comments where necessary

### JavaScript

* Use ES Modules
* Use descriptive naming
* Keep code modular and readable
* Maintain consistent formatting

---

## Pull Request Workflow

1. Fork the repository
2. Create a new branch
3. Make your changes
4. Test your changes
5. Commit using conventional commits
6. Push your branch
7. Open a Pull Request
8. Link the related issue

Example:

```text
Closes #32
```

---

## Documentation Contributions

Documentation improvements are always welcome.

When updating documentation:

* Keep instructions beginner-friendly
* Use clear headings
* Include examples where possible
* Ensure commands are accurate

---

## Code of Conduct

Please be respectful and professional when interacting with maintainers and contributors.

We expect all contributors to foster a welcoming and collaborative environment for everyone.

---

Thank you for helping improve LeadOrbit! 🎉
