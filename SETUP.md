# Setup: hosted database and scheduled runs

Two accounts are needed. Both are free and neither asks for a card.

## 1. Neon (Postgres)

1. Sign up at <https://neon.tech> with GitHub or email.
2. Create a project. Pick region **AWS ap-southeast-1 (Singapore)** — closest
   to Vietnam, so queries from home are quick.
3. On the dashboard, open **Connection string** and copy the `psql` one. It
   looks like:

   ```
   postgresql://neondb_owner:XXXX@ep-something-123.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```

4. Locally, put it in `.env` (this file is gitignored, so the password never
   reaches GitHub):

   ```powershell
   copy .env.example .env
   notepad .env       # paste the string after DATABASE_URL=
   ```

5. Check the connection, then copy the local catalogue up:

   ```powershell
   .\.venv\Scripts\python push_to_postgres.py --check
   .\.venv\Scripts\python push_to_postgres.py
   ```

Neon's free tier gives 0.5 GB per project. The catalogue is well under 1 MB
per crawl, so storage is not a concern for years. Unlike Supabase, Neon does
not pause an idle project, so the nightly run keeps working untouched.

## 2. GitHub Actions

1. Create an empty repository (private is fine) at
   <https://github.com/new>. Do **not** add a README or .gitignore — the local
   repo already has them.
2. Push this folder:

   ```powershell
   git remote add origin https://github.com/<you>/<repo>.git
   git branch -M main
   git push -u origin main
   ```

3. In the repo, go to **Settings → Secrets and variables → Actions → New
   repository secret**:
   - Name: `DATABASE_URL`
   - Value: the same Neon connection string

4. Open the **Actions** tab, pick the **crawl** workflow, and press **Run
   workflow** to test it immediately rather than waiting for the schedule.

The workflow then runs daily at 05:00 Vietnam time. It fails loudly if the
secret is missing, and writes a per-shop summary you can read from the run
page.

## Why run it there and not here

A full pass takes about half an hour of mostly waiting on rate limits. On a
laptop with 8 GB that is half an hour of contention for memory you want for
editing code. GitHub's free tier covers 2000 minutes a month; a nightly run
uses roughly 900 of them, and the laptop stays free.

## Checking the data afterwards

Once `.env` points at Neon, every tool reads from it automatically:

```powershell
.\.venv\Scripts\python main.py --stats
.\.venv\Scripts\python compare.py
```

To go back to the local SQLite copy, comment out `DATABASE_URL` in `.env`.
