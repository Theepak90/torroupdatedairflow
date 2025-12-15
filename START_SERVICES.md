# 🚀 Start All Services - Complete Commands

## Prerequisites
- MySQL must be running
- All `.env` files configured

---

## Terminal 1: Backend API (Port 5001)

```bash
cd /Users/theepak/Desktop/torroairflow/backend
source venv/bin/activate
python -m app.main
```

**Expected output:**
```
 * Running on http://0.0.0.0:5001
```

---

## Terminal 2: Frontend (Port 3000)

```bash
cd /Users/theepak/Desktop/torroairflow/frontend
npm run dev
```

**Expected output:**
```
  VITE v5.x.x  ready in xxx ms
  ➜  Local:   http://localhost:3000/
```

---

## Terminal 3: Airflow Webserver (Port 8081)

```bash
cd /Users/theepak/Desktop/torroairflow/airflow
source venv/bin/activate
export AIRFLOW_HOME=$(pwd)
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
# Using hardcoded Azure MySQL connection (configured in airflow.cfg)
# Can override with: export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="mysql+pymysql://..."
airflow webserver --port 8081
```

**Expected output:**
```
Running the Gunicorn Server with:
Workers: 1 sync
...
Airflow is running at http://0.0.0.0:8081/
```

---

## Terminal 4: Airflow Scheduler

```bash
cd /Users/theepak/Desktop/torroairflow/airflow
source venv/bin/activate
export AIRFLOW_HOME=$(pwd)
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
# Using hardcoded Azure MySQL connection (configured in airflow.cfg)
# Can override with: export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="mysql+pymysql://..."
airflow scheduler
```

**Expected output:**
```
[2025-12-13 ...] {scheduler_job.py:xxx} INFO - Starting the scheduler
```

---

## Quick Start Script (All in One)

Save this as `start_all.sh`:

```bash
#!/bin/bash

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PROJECT_DIR="/Users/theepak/Desktop/torroairflow"

echo -e "${BLUE}Starting all services...${NC}\n"

# Terminal 1: Backend
osascript -e 'tell app "Terminal" to do script "cd '"$PROJECT_DIR"'/backend && source venv/bin/activate && python -m app.main"'

sleep 2

# Terminal 2: Frontend
osascript -e 'tell app "Terminal" to do script "cd '"$PROJECT_DIR"'/frontend && npm run dev"'

sleep 2

# Terminal 3: Airflow Webserver
osascript -e 'tell app "Terminal" to do script "cd '"$PROJECT_DIR"'/airflow && source venv/bin/activate && export AIRFLOW_HOME=\$(pwd) && export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES && MYSQL_PASS=\$(grep MYSQL_PASSWORD .env | cut -d\"=\" -f2) && export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=\"mysql+pymysql://root:\${MYSQL_PASS}@localhost:3306/airflow_metadata\" && airflow webserver --port 8081"'

sleep 2

# Terminal 4: Airflow Scheduler
osascript -e 'tell app "Terminal" to do script "cd '"$PROJECT_DIR"'/airflow && source venv/bin/activate && export AIRFLOW_HOME=\$(pwd) && export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES && MYSQL_PASS=\$(grep MYSQL_PASSWORD .env | cut -d\"=\" -f2) && export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=\"mysql+pymysql://root:\${MYSQL_PASS}@localhost:3306/airflow_metadata\" && airflow scheduler"'

echo -e "${GREEN}All services started in separate Terminal windows!${NC}"
echo -e "\nAccess points:"
echo -e "  Frontend:    http://localhost:3000"
echo -e "  Backend API: http://localhost:5001"
echo -e "  Airflow UI:  http://localhost:8081"
```

Make it executable:
```bash
chmod +x start_all.sh
./start_all.sh
```

---

## Verify Services Are Running

```bash
# Check all ports
lsof -nP -iTCP:5001 -sTCP:LISTEN  # Backend
lsof -nP -iTCP:3000 -sTCP:LISTEN  # Frontend
lsof -nP -iTCP:8081 -sTCP:LISTEN  # Airflow

# Check processes
ps aux | grep "python.*app.main"     # Backend
ps aux | grep "node.*vite"          # Frontend
ps aux | grep "airflow webserver"   # Airflow webserver
ps aux | grep "airflow scheduler"    # Airflow scheduler
```

---

## Stop All Services

```bash
# Kill all services
pkill -f "python.*app.main"
pkill -f "node.*vite"
pkill -f "airflow webserver"
pkill -f "airflow scheduler"

# Or kill by port
lsof -ti:5001 | xargs kill -9
lsof -ti:3000 | xargs kill -9
lsof -ti:8081 | xargs kill -9
```

---

## Access Points

- **Frontend UI:** http://localhost:3000
- **Backend API:** http://localhost:5001
- **Backend Health:** http://localhost:5001/health
- **Airflow UI:** http://localhost:8081 (admin/admin)
- **API Discovery:** http://localhost:5001/api/discovery
- **API Stats:** http://localhost:5001/api/discovery/stats

---

## Troubleshooting

### Backend won't start
- Check MySQL is running: `ps aux | grep mysqld`
- Verify `.env` file exists in `backend/` directory
- Check port 5001 is free: `lsof -i:5001`

### Frontend won't start
- Run `npm install` in `frontend/` directory
- Check port 3000 is free: `lsof -i:3000`

### Airflow won't start
- Verify `AIRFLOW_HOME` is set correctly
- Check MySQL connection string in `.env`
- Verify `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` is set (macOS)
- Check port 8081 is free: `lsof -i:8081`

### DAG not running
- Check scheduler is running: `ps aux | grep "airflow scheduler"`
- Unpause DAG in Airflow UI: http://localhost:8081
- Check DAG logs in Airflow UI

---

**That's it! All services should be running now.** 🎉

