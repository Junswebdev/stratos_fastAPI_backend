# Stratos LMS Backend

Backend API for the Stratos Learning Management System, built with FastAPI and a strict MVC pattern.

## 🚀 Tech Stack

- **Framework:** [FastAPI](https://fastapi.tiangolo.com/)
- **Server:** [Uvicorn](https://www.uvicorn.org/)
- **ORM:** [SQLAlchemy](https://www.sqlalchemy.org/)
- **Database Migrations:** [Alembic](https://alembic.sqlalchemy.org/)
- **Database:** PostgreSQL
- **Authentication:** JWT (JSON Web Tokens)
- **Validation:** [Pydantic](https://docs.pydantic.dev/)

## 📂 Project Structure

```text
stratos_backend/
├── alembic/            # Database migration scripts
├── app/
│   ├── controllers/    # API Routers & Business Logic (The 'C' in MVC)
│   ├── models/         # SQLAlchemy Database Models (The 'M' in MVC)
│   ├── views/          # Pydantic Schemas (The 'V' in MVC)
│   ├── utils/          # Utility functions & helpers
│   ├── database.py     # Database connection & session management
│   └── main.py         # Application entry point
├── .env                # Environment variables
├── alembic.ini         # Alembic configuration
└── requirements.txt    # Project dependencies
```

## 🛠️ Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd stratos/stratos_backend
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables:**
   Create a `.env` file in the root of the `stratos_backend` directory:
   ```env
   DATABASE_URL=postgresql://user:password@localhost:5432/stratos_db
   SECRET_KEY=your_super_secret_key
   ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=30
   ```

### Database Setup & Migrations

1. **Create the database** in PostgreSQL.
2. **Run migrations** to create the tables:
   ```bash
   alembic upgrade head
   ```

## 🏃 Running the Application

Start the development server:

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.

## 📖 API Documentation

FastAPI provides interactive API documentation automatically:

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

## 🧪 Key Endpoints

- `POST /auth/register`: Register a new user
- `POST /auth/login`: Login and receive an access token
- `GET /api/v1/health`: Health check
- `GET /api/v1/courses`: List all courses
- `POST /api/v1/courses`: Create a new course (Teacher only)
