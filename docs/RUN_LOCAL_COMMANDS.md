# Local Run Commands

Run these from PowerShell.

## 1. Start Backend

```powershell
$ports = @(8000); foreach ($port in $ports) { $pids = (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique; foreach ($pid in $pids) { if ($pid) { taskkill /PID $pid /F } } }

cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Backend URL:

```text
http://127.0.0.1:8000
```

## 2. Start Frontend

```powershell
$ports = @(3000,3001); foreach ($port in $ports) { $pids = (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique; foreach ($pid in $pids) { if ($pid) { taskkill /PID $pid /F } } }

cd C:\Users\LENOVO\Downloads\Panopticon\frontend
npm.cmd run dev
```

Frontend URL:

```text
http://localhost:3000
```

If Next.js says port `3000` is busy and starts on `3001`, open:

```text
http://localhost:3001
```

## 3. Optional Agent Runtime Smoke Test

Run after the backend is already running.

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
python scripts/smoke_agent_runtime.py --list-tools
python scripts/smoke_agent_runtime.py --question "Which risks should I inspect first?"
```
