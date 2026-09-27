CREATE INDEX observations_revision ON observations(revision_id);
CREATE INDEX jobs_stream_state ON jobs(stream_key, state, updated_at);
