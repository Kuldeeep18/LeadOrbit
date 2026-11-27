# Contributing to LeadOrbit

Thank you for your interest in contributing to LeadOrbit! 🚀

We welcome contributions of all sizes, including bug fixes, documentation improvements, feature enhancements, testing, and UI updates.

---

## Contribution Rules (Issue-First Workflow)

**Please open or get assigned to an issue *before* raising a Pull Request.**

1. **Star & Fork**: Star ⭐ this repository and fork it to your GitHub account.
2. **Open or Claim an Issue First**:
   * **Existing issue**: Browse the open issues and comment `/assign` (optionally with your short implementation plan). If you have starred the repo and don't already have an active assigned issue, our automation bot will assign it to you quickly! To keep things fair, contributors are assigned **one open issue at a time**.
   * **New bug or feature**: If the change is not covered by an existing issue, **open a new issue first** using our Bug Report or Feature Request template and wait for maintainer approval/assignment before writing code.
   * **No unsolicited PRs**: Pull Requests without a linked, approved/assigned issue (`Closes #<issue-number>`) will not be merged.
3. **Human Review, CI & Rate Limits**:
   * Purely automated or AI-dumped PRs are not accepted. Contributors must test changes locally, understand every line they submit, and pass all CI checks.
   * **Max 2 PRs per day**: To ensure steady, high-quality reviews and fair participation, at most **2 Pull Requests per contributor can be merged per day** (UTC). Extra eligible PRs wait automatically until the next day.

---

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

Copy the example environment file and fill in your values:

```bash
cp backend/.env.example backend/.env
```

Then edit `backend/.env` and add the required values (Google OAuth, Celery, Gemini API, etc.) as described in the file comments.

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

1. **Open an issue first** (using the Bug Report / Feature Request template) or claim an existing open issue and wait for maintainer assignment
2. Star and fork the repository
3. Create a new branch from `main` (e.g., `fix/135-duplicate-title-tags`)
4. Make your changes cleanly and test them locally
5. Commit using conventional commits
6. Push your branch to your fork
7. Open a Pull Request, fill out the PR template, and link the related issue (`Closes #<issue-number>`)
8. Respond to maintainer feedback and verification questions during review

> ⚠️ **Important:** Do **not** raise a PR directly without first opening an issue (or being assigned to an existing one). Unlinked PRs without prior issue approval will not be merged.

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
