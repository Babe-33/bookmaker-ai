// This service worker makes the app installable. Look Mom, no internet! (Actually we need internet for the AI, but it's required for PWA installation)
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open('bookmaker-ai-v1').then((cache) => {
            return cache.addAll([
                '/',
                '/static/index.html',
                '/static/style.css',
                '/static/app.js',
                '/static/manifest.json'
            ]);
        })
    );
});

self.addEventListener('fetch', (event) => {
    event.respondWith(
        caches.match(event.request).then((response) => {
            return response || fetch(event.request);
        })
    );
});
