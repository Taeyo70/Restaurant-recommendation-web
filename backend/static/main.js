/* ==========================================================================
   FoodFinder Interactive JavaScript & Animation Engine
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {

    // ----------------------------------------------------------------------
    // 1. Scroll Reveal Observer (Smooth Fade & Scale Entrance)
    // ----------------------------------------------------------------------
    const revealElements = document.querySelectorAll('.stat-card, .analytics-card, .restaurant-card, .dashboard-title, .search-header-container');

    const revealObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach((entry, index) => {
            if (entry.isIntersecting) {
                // Staggered reveal delay
                setTimeout(() => {
                    entry.target.classList.add('active');
                }, (index % 4) * 80);
                observer.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.1,
        rootMargin: '0px 0px -40px 0px'
    });

    revealElements.forEach(el => {
        el.classList.add('reveal');
        revealObserver.observe(el);
    });


    // ----------------------------------------------------------------------
    // 2. Interactive Canvas Frame Animation (Pizza Showcase)
    // ----------------------------------------------------------------------
    const canvas = document.getElementById('heroFrameCanvas');
    if (canvas) {
        const ctx = canvas.getContext('2d');
        const framePaths = [
            canvas.dataset.frame1 || "/static/images/frame1.jpg",
            canvas.dataset.frame2 || "/static/images/frame2.jpg",
            canvas.dataset.frame3 || "/static/images/frame3.jpg",
            canvas.dataset.frame4 || "/static/images/frame4.jpg",
            canvas.dataset.frame5 || "/static/images/frame5.jpg"
        ];
        const fallbackPaths = [
            canvas.dataset.fallback1 || "/static/images/frame1.jpg",
            canvas.dataset.fallback2 || "/static/images/frame2.jpg",
            canvas.dataset.fallback3 || "/static/images/frame3.jpg",
            canvas.dataset.fallback4 || "/static/images/frame4.jpg",
            canvas.dataset.fallback5 || "/static/images/frame5.jpg"
        ];

        const images = [];
        let loadedCount = 0;
        let isPlaying = true;
        let speed = 0.022; // Frame crossfade step speed

        framePaths.forEach((path, i) => {
            const img = new Image();
            img.src = path;
            img.onerror = () => {
                if (img.src !== new URL(fallbackPaths[i], window.location.href).href) {
                    img.src = fallbackPaths[i];
                }
            };
            img.onload = () => {
                loadedCount++;
                if (loadedCount === 1 && i === 0) {
                    drawFrame(0, 1);
                }
            };
            images.push(img);
        });

        let currentFrameIndex = 0;
        let progress = 0;
        let animationFrameId = null;

        function drawFrame(frameIdx, opacity = 1) {
            const img = images[frameIdx];
            if (!img || !img.complete) return;
            ctx.globalAlpha = opacity;
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        }

        function renderLoop() {
            if (loadedCount > 0 && isPlaying) {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                const nextFrameIndex = (currentFrameIndex + 1) % images.length;
                
                drawFrame(currentFrameIndex, 1);
                if (images[nextFrameIndex] && images[nextFrameIndex].complete) {
                    drawFrame(nextFrameIndex, progress);
                }

                progress += speed;
                if (progress >= 1) {
                    progress = 0;
                    currentFrameIndex = nextFrameIndex;
                }
            }
            animationFrameId = requestAnimationFrame(renderLoop);
        }

        requestAnimationFrame(renderLoop);

        // 3D Parallax Mouse Move effect on Canvas Wrapper
        const heroWrapper = document.querySelector('.hero-animation-wrapper');
        if (heroWrapper) {
            heroWrapper.addEventListener('mousemove', (e) => {
                const rect = heroWrapper.getBoundingClientRect();
                const x = e.clientX - rect.left - (rect.width / 2);
                const y = e.clientY - rect.top - (rect.height / 2);
                const rotateX = (-y / rect.height) * 14;
                const rotateY = (x / rect.width) * 14;
                
                canvas.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(1.03)`;
            });

            heroWrapper.addEventListener('mouseleave', () => {
                canvas.style.transform = 'perspective(1000px) rotateX(0deg) rotateY(0deg) scale(1)';
            });
        }
    }


    // ----------------------------------------------------------------------
    // 3. Heart / Favorite Button Toggle & Local Storage
    // ----------------------------------------------------------------------
    const favoriteButtons = document.querySelectorAll('.favorite-btn');
    const readFavorites = () => JSON.parse(
        localStorage.getItem('foodfinder_favorites') || '[]'
    );
    const favoriteId = (favorite) => (
        typeof favorite === 'string' ? favorite : favorite.id
    );
    const savedFavorites = readFavorites();

    favoriteButtons.forEach(btn => {
        const id = btn.dataset.id;
        if (savedFavorites.some((favorite) => favoriteId(favorite) === id)) {
            btn.classList.add('active');
        }

        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            
            const currentFavs = readFavorites();
            if (btn.classList.contains('active')) {
                btn.classList.remove('active');
                const updated = currentFavs.filter(
                    (favorite) => favoriteId(favorite) !== id
                );
                localStorage.setItem('foodfinder_favorites', JSON.stringify(updated));
                showToast('Removed from favorites 💔');
            } else {
                btn.classList.add('active');
                currentFavs.push({
                    id,
                    name: btn.dataset.name,
                    city: btn.dataset.city,
                    location: btn.dataset.location,
                    cuisine: btn.dataset.cuisine,
                    rating: btn.dataset.rating,
                    cost: btn.dataset.cost,
                    votes: btn.dataset.votes,
                    map: btn.dataset.map
                });
                localStorage.setItem('foodfinder_favorites', JSON.stringify(currentFavs));
                showToast('Saved to your favorites! ❤️');
                btn.style.transform = 'scale(1.35)';
                setTimeout(() => btn.style.transform = '', 200);
            }
        });
    });

    // ----------------------------------------------------------------------
    // 4. Favorites Page Renderer
    // ----------------------------------------------------------------------
    const favoritesList = document.getElementById('favorites-list');
    const favoritesEmpty = document.getElementById('favorites-empty');
    if (favoritesList) {
        const escapeHtml = (value) => String(value || '').replace(/[&<>"']/g, (char) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        }[char]));

        const favorites = readFavorites().filter(
            (favorite) => typeof favorite === 'object' && favorite.name
        );

        if (!favorites.length && favoritesEmpty) {
            favoritesEmpty.hidden = false;
        }

        favorites.forEach((favorite) => {
            const mapLink = favorite.map
                ? `<a href="${escapeHtml(favorite.map)}" target="_blank" rel="noopener" class="map-button">🗺️ View on Google Maps</a>`
                : '';

            favoritesList.insertAdjacentHTML('beforeend', `
                <article class="restaurant-card favorite-card">
                    <div class="restaurant-header-banner">
                        <span class="favorite-city">📍 ${escapeHtml(favorite.city)}</span>
                        <span class="card-rating-pill">★ ${escapeHtml(favorite.rating)}</span>
                    </div>
                    <div class="restaurant-body">
                        <h2 class="restaurant-title">${escapeHtml(favorite.name)}</h2>
                        <p class="location">📍 ${escapeHtml(favorite.location)}</p>
                        <div class="tags"><span>${escapeHtml(favorite.cuisine)}</span></div>
                        <div class="card-footer-info">
                            <div class="cost">₹${escapeHtml(favorite.cost)} <small>for two</small></div>
                            <div class="votes">👥 ${escapeHtml(favorite.votes)} reviews</div>
                        </div>
                        ${mapLink}
                    </div>
                </article>
            `);
        });
    }


    // ----------------------------------------------------------------------
    // 5. Toast Notification Popup
    // ----------------------------------------------------------------------
    function showToast(message) {
        let toast = document.getElementById('toast-notification');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'toast-notification';
            toast.className = 'toast-notification';
            document.body.appendChild(toast);
        }

        toast.textContent = message;
        toast.classList.add('show');

        setTimeout(() => {
            toast.classList.remove('show');
        }, 2600);
    }


    // ----------------------------------------------------------------------
    // 6. Back To Top Floating Button
    // ----------------------------------------------------------------------
    const backToTopBtn = document.createElement('button');
    backToTopBtn.className = 'back-to-top';
    backToTopBtn.innerHTML = '↑';
    backToTopBtn.setAttribute('aria-label', 'Back to top');
    document.body.appendChild(backToTopBtn);

    window.addEventListener('scroll', () => {
        if (window.scrollY > 350) {
            backToTopBtn.classList.add('visible');
        } else {
            backToTopBtn.classList.remove('visible');
        }
    });

    backToTopBtn.addEventListener('click', () => {
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    });


    // ----------------------------------------------------------------------
    // 7. Header Glassmorphism Scroll Effect
    // ----------------------------------------------------------------------
    const topbar = document.querySelector('.topbar');
    if (topbar) {
        window.addEventListener('scroll', () => {
            if (window.scrollY > 20) {
                topbar.classList.add('scrolled');
            } else {
                topbar.classList.remove('scrolled');
            }
        });
    }

});
