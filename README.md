# Scraply AI Agent

An intelligent AI agent system that automatically evaluates pickup requests and illegal dumping reports for the Scraply waste management platform.

## Features

- **Pickup Request Evaluation**: Validates pickup requests, detects duplicates, and identifies spam
- **Illegal Dumping Evaluation**: Verifies dumping reports and filters false reports
- **Intelligent Picker Assignment**: Selects optimal pickers based on location, vehicle type, and workload
- **Queue-Based Processing**: Processes requests from Redis queues in real-time
- **AI-Powered Decisions**: Uses Groq LLM (Llama 3.3) for intelligent analysis

## Architecture

```
scraply-ai-agent/
├── agents/
│   ├── base_agent.py                 # Base class with LLM integration
│   ├── pickup_evaluation_agent.py    # Evaluates pickup requests
│   ├── illegal_dump_evaluation_agent.py  # Evaluates dump reports
│   ├── picker_assignment_agent.py    # Assigns pickers to requests
│   └── orchestrator_agent.py         # Coordinates the workflow
│
├── services/
│   ├── database_service.py           # Read-only PostgreSQL access
│   ├── redis_service.py              # Queue operations
│   └── rest_api_service.py           # Backend API communication
│
├── utils/
│   ├── geo_utils.py                  # Geographic calculations
│   ├── duplicate_utils.py            # Duplicate detection
│   └── logging_utils.py              # Logging configuration
│
├── config/
│   ├── settings.py                   # Configuration management
│   └── constants.py                  # Enums and constants
│
├── worker/
│   └── main.py                       # Background worker service
│
├── main.py                           # Entry point
├── requirements.txt                  # Python dependencies
└── .env.example                      # Environment template
```

## Processing Workflow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Redis Queue    │────▶│  Orchestrator   │────▶│   Evaluation    │
│  (pickup_queue) │     │     Agent       │     │     Agent       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                │                        │
                                │                        ▼
                                │               ┌─────────────────┐
                                │               │  Valid Request? │
                                │               └─────────────────┘
                                │                   │         │
                                │                   ▼         ▼
                                │             ┌───────┐   ┌────────┐
                                │             │ Valid │   │ Invalid│
                                │             └───────┘   └────────┘
                                │                 │            │
                                ▼                 ▼            ▼
                        ┌─────────────────┐  ┌────────┐  ┌──────────┐
                        │ Picker Assignment│  │Progress│  │ Cancel   │
                        │     Agent        │  │  API   │  │   API    │
                        └─────────────────┘  └────────┘  └──────────┘
                                │
                                ▼
                        ┌─────────────────┐
                        │  Assign Picker  │
                        │     via API     │
                        └─────────────────┘
```

## Queue Structure

The agent listens to four Redis queues:

| Queue Name | Purpose | Action |
|------------|---------|--------|
| `pickup_queue` | New pickup requests | Evaluate validity |
| `dump_queue` | New illegal dump reports | Evaluate validity |
| `pickup_assign_queue` | Valid pickups awaiting assignment | Assign picker |
| `dump_assign_queue` | Valid dumps awaiting assignment | Assign picker |

## Installation

### Prerequisites

- Python 3.10 or higher
- PostgreSQL database with read-only views
- Redis server
- Groq API key

### Setup

1. **Clone and navigate to the agent directory**:
   ```bash
   cd scraply/Agent
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv .venv
   
   # Windows
   .venv\Scripts\activate
   
   # Linux/Mac
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

### Database Views

Create the following read-only views in PostgreSQL:

```sql
-- View for pickup requests
CREATE VIEW view_pickups AS
SELECT 
    p.id,
    p.user_id,
    p.picker_id,
    p.assigned_by,
    p.description,
    p.category,
    p.image_url,
    p.latitude,
    p.longitude,
    p.address,
    p.status,
    p.priority_level,
    p.requested_at,
    p.assigned_at,
    p.completed_at
FROM pickup_requests p;

-- View for illegal dumps
CREATE VIEW view_illegal_dumps AS
SELECT 
    d.id,
    d.description,
    d.category,
    d.latitude,
    d.longitude,
    d.address,
    d.landmark,
    d.image_url,
    d.reported_by AS reported_by_id,
    d.assigned_picker_id,
    d.assigned_by,
    d.status,
    d.priority_level,
    d.reported_at,
    d.assigned_at,
    d.resolved_at
FROM illegal_dumping_requests d;

-- View for users
CREATE VIEW view_users AS
SELECT 
    u.id,
    u.name,
    u.role,
    u.status,
    u.vehicle_type,
    u.pick_up_route,
    u.address,
    u.created_at,
    u.updated_at
FROM users u;

-- Grant permissions to agent user
GRANT SELECT ON view_pickups, view_illegal_dumps, view_users TO scraply_agent;
GRANT USAGE ON SCHEMA public TO scraply_agent;
```

### Agent User Setup

Create an agent user in the database:

```sql
INSERT INTO users (id, name, email, password, role, status, created_at)
VALUES (
    'USR_agent_system_001',
    'AI Agent System',
    'agent@scraply.system',
    'not_used_for_login',
    'AGENT',
    'ACCEPTED',
    NOW()
);
```

Use this user's ID as `AGENT_ID` in your `.env` file.

## Running the Agent

### Start the worker

```bash
python main.py
```

### Or using the module

```bash
python -m worker.main
```

### Run as a service (Linux)

Create a systemd service file `/etc/systemd/system/scraply-agent.service`:

```ini
[Unit]
Description=Scraply AI Agent
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=scraply
WorkingDirectory=/path/to/scraply/Agent
Environment=PATH=/path/to/scraply/Agent/.venv/bin
ExecStart=/path/to/scraply/Agent/.venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable scraply-agent
sudo systemctl start scraply-agent
```

## Configuration Options

| Variable | Description | Default |
|----------|-------------|---------|
| `GROQ_API_KEY` | Groq API key for LLM | Required |
| `GROQ_MODEL` | LLM model to use | `llama-3.3-70b-versatile` |
| `POLL_INTERVAL` | Queue poll interval (seconds) | `5.0` |
| `DUPLICATE_DISTANCE_KM` | Distance threshold for duplicates | `0.5` |
| `DUPLICATE_TIME_HOURS` | Time window for duplicates | `24` |

## Evaluation Criteria

### Pickup Request Evaluation

1. **Spam Detection**
   - Description length < 10 characters
   - Invalid coordinates (0,0)
   - Missing required fields

2. **Duplicate Detection**
   - Geographic proximity (< 0.5km)
   - Similar category
   - Recent time window (< 24h)
   - Description similarity

3. **AI Analysis**
   - Description relevance
   - Category appropriateness
   - Overall validity

### Picker Assignment Criteria

1. **Vehicle Compatibility** (30%)
   - Appropriate vehicle for waste category

2. **Geographic Proximity** (30%)
   - Distance to request location

3. **Route Compatibility** (20%)
   - Request within picker's route

4. **Workload Balance** (20%)
   - Current active assignments

## API Integration

The agent calls these backend endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/agent/pickup` | PUT | Update pickup status |
| `/agent/dumping` | PUT | Update dump status |

### Authentication

Requests include headers:
- `X-ACCESS-KEY`: Agent access key
- `X-SECRET-KEY`: Agent secret key

These must match the values in the backend's `secrets.properties`.

## Logging

Logs are written to stdout with the format:
```
2024-01-15 10:30:45 | INFO     | scraply_agent | [PICKUP] PKP_xxx - Started evaluation
```

## Troubleshooting

### Common Issues

1. **Database connection fails**
   - Check `DB_*` environment variables
   - Ensure views exist
   - Verify read-only user permissions

2. **Redis connection fails**
   - Check `REDIS_*` environment variables
   - Verify Redis is running
   - Check SSL settings if using cloud Redis

3. **API calls fail**
   - Verify `AGENT_ACCESS_KEY` and `AGENT_SECRET_KEY`
   - Ensure backend is running
   - Check `API_BASE_URL`

4. **LLM errors**
   - Verify `GROQ_API_KEY` is valid
   - Check Groq API quotas

## Development

### Running Tests

```bash
# Install dev dependencies
pip install pytest pytest-asyncio

# Run tests
pytest tests/
```

### Code Structure

- **Agents**: Self-contained AI agents with specific responsibilities
- **Services**: External service integrations (DB, Redis, API)
- **Utils**: Helper functions and utilities
- **Worker**: Background processing infrastructure

## License

Copyright (c) 2024 Scraply. All rights reserved.
