-- ===================================================
-- Scraply AI Agent - Database Views Setup
-- ===================================================
-- Run this script as a database administrator to create
-- the required views and read-only user for the AI Agent.
-- ===================================================
REVOKE ALL ON SCHEMA public FROM scraply_agent;

-- Drop existing views if they exist (be careful in production!)
DROP VIEW IF EXISTS view_pickups CASCADE;
DROP VIEW IF EXISTS view_illegal_dumps CASCADE;
DROP VIEW IF EXISTS view_users CASCADE;

-- ===================================================
-- VIEW: view_pickups
-- Read-only view of pickup requests
-- ===================================================
CREATE VIEW view_pickups AS
SELECT 
    p.id,
    p.user_id,
    p.picker_id,
    p.assigned_by,
    p.description,
    p.category,
    p.image_url AS image_url,
    p.latitude,
    p.longitude,
    p.address,
    p.status,
    p.priority_level,
    p.requested_at,
    p.assigned_at,
    p.completed_at
FROM pickup_requests p;

COMMENT ON VIEW view_pickups IS 'Read-only view of pickup requests for AI Agent';

-- ===================================================
-- VIEW: view_illegal_dumps
-- Read-only view of illegal dumping reports
-- ===================================================
CREATE VIEW view_illegal_dumps AS
SELECT 
    d.id,
    d.description,
    d.category,
    d.latitude,
    d.longitude,
    d.address,
    d.landmark,
    d.image_url AS image_url,
    d.reported_by AS reported_by_id,
    d.assigned_picker_id,
    d.assigned_by,
    d.status,
    d.priority_level,
    d.reported_at,
    d.assigned_at,
    d.resolved_at
FROM illegal_dumping_requests d;

COMMENT ON VIEW view_illegal_dumps IS 'Read-only view of illegal dumping reports for AI Agent';

-- ===================================================
-- VIEW: view_users
-- Read-only view of users (pickers and others)
-- ===================================================
CREATE VIEW view_users AS
SELECT 
    u.id,
    u.name,
    u.role,
    u.status,
    u.vehicle_type AS vehicle_type,
    u.pick_up_route AS pick_up_route,
    u.address,
    u.created_at,
    u.updated_at
FROM users u;

COMMENT ON VIEW view_users IS 'Read-only view of users for AI Agent';

-- ===================================================
-- Grant permissions to scraply_agent user
-- ===================================================
GRANT SELECT ON view_pickups TO scraply_agent;
GRANT SELECT ON view_illegal_dumps TO scraply_agent;
GRANT SELECT ON view_users TO scraply_agent;
GRANT USAGE ON SCHEMA public TO scraply_agent;

-- ===================================================
-- Verification queries
-- ===================================================
SELECT 
    table_name, 
    table_type 
FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name LIKE 'view_%';

SELECT 
    grantee, 
    table_name, 
    privilege_type 
FROM information_schema.table_privileges 
WHERE grantee = 'scraply_agent';

SELECT id, name, role, status 
FROM users 
WHERE role = 'AGENT';

SELECT 'Database setup complete!' AS status;
