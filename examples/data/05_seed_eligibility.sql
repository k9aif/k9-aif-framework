-- Eligibility Checks (Austin Members)
INSERT INTO eligibility_checks (member_id, plan, verified_by, verified_at, status)
VALUES
('M1001', 'Acme Gold Plan', 'system', datetime('now'), 'eligible'),
('M1002', 'Acme Silver Plan', 'system', datetime('now'), 'eligible');