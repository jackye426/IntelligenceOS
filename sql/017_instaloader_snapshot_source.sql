-- Preserve original sources and admit separately attributable Instagram observations.
BEGIN;
ALTER TABLE public.content_metric_snapshots DROP CONSTRAINT content_metric_snapshots_source_check;
ALTER TABLE public.content_metric_snapshots ADD CONSTRAINT content_metric_snapshots_source_check
 CHECK (source IN ('display_api', 'yt_dlp', 'studio_item_list', 'manual', 'instaloader'));
-- Fresh observations are distinct from the backwards-compatible content cache.
CREATE VIEW public.latest_social_metric_snapshots WITH (security_invoker=true) AS
SELECT DISTINCT ON (s.platform, s.platform_post_id, s.source)
       s.platform, s.platform_post_id, p.account_handle, p.owner_scope, s.source, s.captured_at, s.metrics
FROM public.content_metric_snapshots s
JOIN public.content_posts p ON p.id = s.content_post_id
WHERE s.source IN ('yt_dlp', 'instaloader')
ORDER BY s.platform, s.platform_post_id, s.source, s.captured_at DESC, s.id DESC;
REVOKE ALL ON public.latest_social_metric_snapshots FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.latest_social_metric_snapshots TO service_role;
COMMIT;
