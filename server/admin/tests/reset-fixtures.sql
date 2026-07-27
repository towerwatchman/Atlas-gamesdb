-- Reset the scratch database to the fixture set the JS suites expect.
-- FK-safe order: children first. Never reassigns source rows onto fixture
-- games -- that silently changes what the search tests are asserting.
DELETE FROM atlas_manual_links;
DELETE FROM atlas_audit;
DELETE FROM f95_zone   WHERE atlas_id > 6 OR atlas_id IS NULL;
DELETE FROM lewdcorner WHERE atlas_id > 6 OR atlas_id IS NULL;
DELETE FROM atlas      WHERE atlas_id > 6;
-- A second f95 row on atlas 1, so the "several source rows" cases have data.
INSERT INTO f95_zone (f95_id, atlas_id, site_url, last_record_update)
VALUES (777001, 1, 'https://f95zone.to/threads/second-mapping.777001/', 1)
ON DUPLICATE KEY UPDATE atlas_id = 1;
