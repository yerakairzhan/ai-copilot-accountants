# AI Copilot for Accountants - MVP Report

## Project Overview

**AI Copilot for Accountants** is an MVP web application for accountants working with individual entrepreneurs in Kazakhstan. The system helps import Kaspi bank statements, classify transactions with an LLM suggestion, calculate USN tax, detect tax risks, attach supporting documents, export a PDF tax package, and keep an audit trail.

The product follows a **human-in-the-loop** approach: AI can suggest and explain, but the accountant reviews and confirms decisions.

## MVP Functionalities - 10 Points

The MVP includes more than three required functional areas: authentication, profile/client management, and the main accounting workflow.

### 1. Authentication

- Login page with email and password.
- Protected dashboard, period pages, and audit log.
- Cookie-based authenticated session.
- Logout action that clears the authentication cookie.

Implemented routes:

- `GET /login`
- `POST /login`
- `GET /logout`

### 2. User Profile / Client Profile Management

The authenticated accountant can manage client profiles for individual entrepreneurs.

- Create client profile with name, BIN/IIN, and tax regime.
- View all client profiles on the dashboard.
- Connect each reporting period to a selected client profile.

Implemented route:

- `POST /clients/create`

### 3. Reporting Period Management

- Create tax reporting periods by client, quarter, and year.
- View all periods on the dashboard.
- Open a detailed workspace for a selected period.

Implemented routes:

- `POST /periods/create`
- `GET /period/{period_id}`

### 4. Bank Statement and Document Upload

- Upload Kaspi Business statements in `.xlsx`, `.xls`, or `.pdf` format.
- Parse transactions from statement files.
- Upload supporting documents such as invoices, acts, contracts, PDFs, images, and spreadsheets.
- Store uploaded file metadata in the database.

Implemented routes:

- `POST /period/{period_id}/upload-statement`
- `POST /period/{period_id}/upload-document`

### 5. AI Transaction Classification

- Classify imported transactions using the configured LLM provider.
- Save AI category suggestion, confidence, and reasoning.
- Mark low-confidence results as needing accountant review.
- Keep final approval manual.

Implemented route:

- `POST /period/{period_id}/classify-all`

### 6. Accountant Review and Approval

- Accountant can approve or edit each transaction category.
- Supported categories: `income`, `expense`, and `personal`.
- System records who approved the transaction and when.
- Approved transactions are used in tax summary calculation.

Implemented routes:

- `GET /api/transaction/{tx_id}`
- `POST /transaction/{tx_id}/approve`

### 7. Tax Risk Analysis

- Deterministic rule engine detects risks without relying on LLM decisions.
- Example risks include large cash withdrawals, missing documents, unclassified transactions, round amounts, and unknown counterparties.
- Accountant can mark risks as resolved or ignored.
- LLM can explain detected risks in plain language.

Implemented routes:

- `POST /period/{period_id}/analyze-risks`
- `GET /risk/{risk_id}/explain`
- `POST /risk/{risk_id}/resolve`

### 8. Tax Summary and PDF Export

- Calculates income, expenses, personal transactions, unclassified transactions, and USN tax.
- Generates a PDF tax package with summary, transactions, and risk list.

Implemented route:

- `GET /period/{period_id}/export-pdf`

### 9. Audit Log

- Logs important actions such as client creation, period creation, statement upload, classification, transaction approval, risk analysis, risk resolution, and PDF export.
- Displays latest audit events for accountant review.

Implemented route:

- `GET /period/{period_id}/audit`

## Architecture - 4 Points

### Use Case Diagram

```mermaid
flowchart LR
    Accountant((Accountant))
    LLM((LLM Provider))
    DB[(SQLite Database)]

    Accountant --> Login[Login / Logout]
    Accountant --> ManageClients[Manage Client Profiles]
    Accountant --> ManagePeriods[Manage Reporting Periods]
    Accountant --> UploadStatements[Upload Bank Statements]
    Accountant --> UploadDocs[Upload Supporting Documents]
    Accountant --> Classify[Request AI Classification]
    Accountant --> Approve[Approve or Edit Transactions]
    Accountant --> AnalyzeRisks[Run Risk Analysis]
    Accountant --> ResolveRisks[Resolve or Ignore Risks]
    Accountant --> ExportPDF[Export Tax PDF]
    Accountant --> ViewAudit[View Audit Log]

    Classify --> LLM
    AnalyzeRisks --> DB
    ExportPDF --> DB
    ViewAudit --> DB
```

### Sequence Diagram

Main flow: accountant uploads a bank statement, classifies transactions, approves them, analyzes risks, and exports a PDF.

```mermaid
sequenceDiagram
    actor Accountant
    participant Web as FastAPI App
    participant Parser as Kaspi Parser
    participant Classifier as Transaction Classifier
    participant Risk as Risk Engine
    participant PDF as PDF Generator
    participant DB as SQLite DB
    participant LLM as LLM Provider

    Accountant->>Web: Login
    Web->>Web: Validate credentials and set cookie
    Accountant->>Web: Upload Kaspi statement
    Web->>Parser: Parse Excel/PDF file
    Parser-->>Web: Parsed transactions
    Web->>DB: Save transactions
    Accountant->>Web: Classify all transactions
    Web->>Classifier: classify_transaction(tx)
    Classifier->>LLM: Ask for category suggestion
    LLM-->>Classifier: JSON suggestion
    Classifier-->>Web: Category, confidence, reasoning
    Web->>DB: Save AI suggestions
    Accountant->>Web: Approve/edit transaction category
    Web->>DB: Save final accountant decision
    Accountant->>Web: Run risk analysis
    Web->>Risk: analyze_risks(transactions, documents)
    Risk-->>Web: Detected risks
    Web->>DB: Save risks
    Accountant->>Web: Export PDF
    Web->>DB: Load period, transactions, risks, summary
    Web->>PDF: Generate tax package
    PDF-->>Web: PDF file path
    Web-->>Accountant: Download PDF
```

### Class Diagram

```mermaid
classDiagram
    class FastAPIApp {
        +dashboard()
        +create_client()
        +create_period()
        +upload_statement()
        +classify_all()
        +approve_transaction()
        +run_risk_analysis()
        +export_pdf()
    }

    class Database {
        +get_connection()
        +init_db()
        +log_action()
        +get_period_with_client()
        +get_transactions()
        +get_risks()
        +calculate_tax_summary()
    }

    class KaspiParser {
        +parse_kaspi_excel(file_path)
        +parse_kaspi_pdf(file_path)
    }

    class TransactionClassifier {
        +classify_transaction(transaction)
        +classify_batch(transactions)
    }

    class RiskEngine {
        +analyze_risks(transactions, documents)
        +explain_risk(risk, transaction)
    }

    class PDFGenerator {
        +generate_tax_package(output_path, client, period, transactions, risks, summary)
    }

    class LLMClient {
        +generate_text(prompt, max_tokens, temperature)
    }

    FastAPIApp --> Database
    FastAPIApp --> KaspiParser
    FastAPIApp --> TransactionClassifier
    FastAPIApp --> RiskEngine
    FastAPIApp --> PDFGenerator
    TransactionClassifier --> LLMClient
    RiskEngine --> LLMClient
```

### ER Diagram

```mermaid
erDiagram
    CLIENTS ||--o{ PERIODS : has
    PERIODS ||--o{ TRANSACTIONS : contains
    PERIODS ||--o{ DOCUMENTS : has
    PERIODS ||--o{ RISKS : has
    TRANSACTIONS ||--o{ DOCUMENTS : supports
    TRANSACTIONS ||--o{ RISKS : triggers

    CLIENTS {
        integer id PK
        text name
        text bin
        text tax_regime
        timestamp created_at
    }

    PERIODS {
        integer id PK
        integer client_id FK
        text quarter
        integer year
        text status
        timestamp created_at
    }

    TRANSACTIONS {
        integer id PK
        integer period_id FK
        text date
        real amount
        text direction
        text counterparty
        text description
        text raw_data
        text category
        text subcategory
        text llm_suggestion
        real llm_confidence
        text llm_reasoning
        integer needs_review
        text approved_by
        timestamp approved_at
    }

    DOCUMENTS {
        integer id PK
        integer transaction_id FK
        integer period_id FK
        text file_name
        text file_path
        text file_type
        timestamp uploaded_at
    }

    RISKS {
        integer id PK
        integer period_id FK
        integer transaction_id FK
        text risk_type
        text severity
        text description
        text llm_explanation
        text status
        text resolved_by
        timestamp resolved_at
    }

    AUDIT_LOG {
        integer id PK
        text user_id
        text action
        text entity_type
        integer entity_id
        text details
        timestamp timestamp
    }
```

## Used Technologies - 2 Points

### Backend

- **Python 3.11+** - main programming language.
- **FastAPI** - web framework and route handling.
- **Uvicorn** - ASGI development server.
- **Jinja2** - HTML template rendering.
- **SQLite** - local relational database.
- **python-dotenv** - environment variable loading.

### Data Processing

- **openpyxl** - parsing Kaspi Excel statements.
- **pdfplumber** - parsing PDF bank statements.
- **ReportLab** - generating PDF tax packages.

### AI / LLM

- **Gemini API** or **Anthropic API** - LLM-based transaction classification and risk explanation.
- Local fallback logic when an LLM provider is unavailable or returns invalid data.

### Frontend

- **HTML templates** - dashboard, period workspace, login, audit pages.
- **CSS** - custom styling in `static/css/main.css`.
- **JavaScript Fetch API** - async form submission, uploads, classification, approval, and risk actions.

### Storage

- **SQLite tables**: `clients`, `periods`, `transactions`, `documents`, `risks`, and `audit_log`.
- **Local filesystem**: uploaded statements/documents in `data/uploads` and generated PDFs in `data/exports`.

## Scoring Summary

| Criteria | Evidence | Points |
|---|---|---:|
| MVP functionalities | Authentication, client/user profile management, periods, uploads, AI classification, review, risk analysis, PDF export, audit log | 10 |
| Architecture | Use-case, sequence, class, and ER diagrams | 4 |
| Used technologies | Backend, frontend, database, AI, data processing, PDF generation | 2 |
| **Total** |  | **16** |
