-- Initial Sample Claims
INSERT INTO claims (claim_id, member_id, provider, amount, status, submitted_at)
VALUES
('C3001', 'M1001', 'CityCare Hospital', 860.75, 'submitted', datetime('now')),
('C3002', 'M1002', 'Travis Family Clinic', 320.00, 'processed', datetime('now')),
('C3003', 'M1003', 'Blue River Pediatrics', 155.50, 'approved', datetime('now'));