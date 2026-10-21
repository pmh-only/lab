\set ON_ERROR_STOP on
\getenv owner_name GUACAMOLE_ADMIN_USERNAME
\getenv owner_password GUACAMOLE_ADMIN_PASSWORD
SELECT pg_advisory_lock(hashtextextended('lab-guacamole-initialize',0));

SELECT to_regclass('public.guacamole_entity') IS NULL AS initialize \gset
\if :initialize
BEGIN;
\i /schema/schema.sql

-- The upstream default account must never be publicly usable. Replace its
-- default password even when disabling it, and preserve existing users on rerun.
SELECT encode(sha256(convert_to(gen_random_uuid()::text, 'UTF8')), 'hex') AS salt \gset
UPDATE guacamole_user
SET password_salt = decode(:'salt','hex'),
    password_hash = sha256(convert_to(:'owner_password' || upper(:'salt'), 'UTF8')),
    password_date = CURRENT_TIMESTAMP,
    disabled = (:'owner_name' <> 'guacadmin')
WHERE entity_id = (SELECT entity_id FROM guacamole_entity WHERE name='guacadmin' AND type='USER');

INSERT INTO guacamole_entity (name,type)
SELECT :'owner_name','USER'
WHERE NOT EXISTS (SELECT FROM guacamole_entity WHERE name=:'owner_name' AND type='USER');

INSERT INTO guacamole_user (entity_id,password_salt,password_hash,password_date)
SELECT entity_id,decode(:'salt','hex'),sha256(convert_to(:'owner_password' || upper(:'salt'), 'UTF8')),CURRENT_TIMESTAMP
FROM guacamole_entity e WHERE name=:'owner_name' AND type='USER'
AND NOT EXISTS (SELECT FROM guacamole_user u WHERE u.entity_id=e.entity_id);

INSERT INTO guacamole_system_permission (entity_id,permission)
SELECT entity_id,'ADMINISTER' FROM guacamole_entity e WHERE name=:'owner_name' AND type='USER'
AND NOT EXISTS (SELECT FROM guacamole_system_permission p WHERE p.entity_id=e.entity_id AND p.permission='ADMINISTER');
COMMIT;
\endif

SELECT EXISTS(SELECT FROM guacamole_entity e JOIN guacamole_system_permission p USING(entity_id)
WHERE e.name=:'owner_name' AND e.type='USER' AND p.permission='ADMINISTER') AS owner_exists \gset
\if :owner_exists
SELECT 'Guacamole schema and original OIDC owner initialized; existing accounts preserved';
\else
\quit 1
\endif
