-- Catalogue Manager SQLite Schema
-- Generated from SQLAlchemy models

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_tag VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL DEFAULT '',
    post_count INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    note TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_series_series_tag ON series (series_tag);
CREATE INDEX IF NOT EXISTS ix_series_status ON series (status);

CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id INTEGER NOT NULL,
    character_tag VARCHAR(255) NOT NULL,
    display_name VARCHAR(255) NOT NULL DEFAULT '',
    danbooru_url VARCHAR(512),
    post_count INTEGER NOT NULL DEFAULT 0,
    multi_color_hair TEXT,
    hair_color TEXT,
    hair_shape TEXT,
    eye_color TEXT,
    feature_tags TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'needs_check',
    from_wiki BOOLEAN NOT NULL DEFAULT 0,
    from_list_page BOOLEAN NOT NULL DEFAULT 0,
    from_posts BOOLEAN NOT NULL DEFAULT 0,
    from_related BOOLEAN NOT NULL DEFAULT 0,
    needs_check_reason TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (series_id) REFERENCES series (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_characters_series_id ON characters (series_id);
CREATE INDEX IF NOT EXISTS ix_characters_character_tag ON characters (character_tag);
CREATE INDEX IF NOT EXISTS ix_characters_status ON characters (status);

CREATE TABLE IF NOT EXISTS generation_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    prompt_level INTEGER NOT NULL DEFAULT 1,
    prompt TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT,
    count INTEGER NOT NULL DEFAULT 1,
    output_path VARCHAR(512),
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_generation_jobs_character_id ON generation_jobs (character_id);
CREATE INDEX IF NOT EXISTS ix_generation_jobs_status ON generation_jobs (status);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    generation_job_id INTEGER,
    image_path VARCHAR(512) NOT NULL,
    auto_tags TEXT,
    auto_status VARCHAR(50),
    hair_match BOOLEAN,
    eye_match BOOLEAN,
    gender_pred VARCHAR(50),
    cover_score REAL,
    is_rejected BOOLEAN NOT NULL DEFAULT 0,
    is_cover BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters (id) ON DELETE CASCADE,
    FOREIGN KEY (generation_job_id) REFERENCES generation_jobs (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_images_character_id ON images (character_id);
CREATE INDEX IF NOT EXISTS ix_images_generation_job_id ON images (generation_job_id);
CREATE INDEX IF NOT EXISTS ix_images_auto_status ON images (auto_status);
CREATE INDEX IF NOT EXISTS ix_images_is_cover ON images (is_cover);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL UNIQUE,
    cover_image_id INTEGER,
    gender VARCHAR(50),
    type VARCHAR(50),
    rating INTEGER,
    final_prompt TEXT,
    review_status VARCHAR(50) NOT NULL DEFAULT 'pending',
    review_note TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters (id) ON DELETE CASCADE,
    FOREIGN KEY (cover_image_id) REFERENCES images (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_reviews_character_id ON reviews (character_id);
CREATE INDEX IF NOT EXISTS ix_reviews_review_status ON reviews (review_status);

CREATE TABLE IF NOT EXISTS settings (
    key VARCHAR(255) PRIMARY KEY,
    value TEXT,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
