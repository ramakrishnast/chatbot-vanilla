-- Runs once, when the data volume is first created.
-- A separate database for the backend test suite, so tests never touch chat history.
CREATE DATABASE chat_test;
