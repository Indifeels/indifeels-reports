report-phone-push (deployed v3): the public-key and check endpoints now send CORS headers
(Access-Control-Allow-Origin: *, OPTIONS handled). Before this, the browser blocked the
"Enable phone notifications" key request with "Failed to fetch", so nobody could subscribe.
