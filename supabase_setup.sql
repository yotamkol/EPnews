-- EP Feed: Supabase Database Setup
-- Run this in your Supabase SQL Editor (https://supabase.com/dashboard)

-- ─────────────────────────────────────
-- Starred articles
-- ─────────────────────────────────────

CREATE TABLE starred_articles (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    paper_link_id TEXT NOT NULL,
    paper_title TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, paper_link_id)
);

ALTER TABLE starred_articles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own stars"
    ON starred_articles FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own stars"
    ON starred_articles FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete own stars"
    ON starred_articles FOR DELETE
    USING (auth.uid() = user_id);

CREATE INDEX idx_starred_user ON starred_articles(user_id);

-- ─────────────────────────────────────
-- Discussions
-- ─────────────────────────────────────

CREATE TABLE discussions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    paper_link_id TEXT UNIQUE NOT NULL,
    comment_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE discussions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Anyone can read discussions"
    ON discussions FOR SELECT
    USING (true);

CREATE POLICY "Auth users can create discussions"
    ON discussions FOR INSERT
    WITH CHECK (auth.role() = 'authenticated');

-- ─────────────────────────────────────
-- Comments (threaded)
-- ─────────────────────────────────────

CREATE TABLE comments (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    discussion_id UUID REFERENCES discussions(id) ON DELETE CASCADE NOT NULL,
    parent_id UUID REFERENCES comments(id) ON DELETE CASCADE,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    user_email TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE comments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Anyone can read comments"
    ON comments FOR SELECT
    USING (true);

CREATE POLICY "Users can create comments"
    ON comments FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own comments"
    ON comments FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own comments"
    ON comments FOR DELETE
    USING (auth.uid() = user_id);

CREATE INDEX idx_comments_discussion ON comments(discussion_id);
CREATE INDEX idx_comments_parent ON comments(parent_id);

-- ─────────────────────────────────────
-- Auto-update comment count trigger
-- ─────────────────────────────────────

CREATE OR REPLACE FUNCTION update_comment_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE discussions SET comment_count = comment_count + 1
        WHERE id = NEW.discussion_id;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE discussions SET comment_count = comment_count - 1
        WHERE id = OLD.discussion_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER comments_count_trigger
    AFTER INSERT OR DELETE ON comments
    FOR EACH ROW EXECUTE FUNCTION update_comment_count();
