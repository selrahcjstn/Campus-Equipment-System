/* Reveal on upward scroll, hide on downward scroll, and always show near the top. */
const landingHeader = document.querySelector('.landing-header');
if (landingHeader) {
    let previousPosition = Math.max(0, window.scrollY);
    let scheduled = false;

    const updateHeader = () => {
        // Clamp overscroll so mobile bounce does not reverse the header state.
        const maximum = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
        const position = Math.min(maximum, Math.max(0, window.scrollY));
        const difference = position - previousPosition;
        if (position <= landingHeader.offsetHeight) {
            landingHeader.classList.remove('is-scroll-hidden');
            previousPosition = position;
        } else if (Math.abs(difference) >= 8) {
            landingHeader.classList.toggle('is-scroll-hidden', difference > 0);
            previousPosition = position;
        }
        scheduled = false;
    };

    window.addEventListener('scroll', () => {
        if (!scheduled) {
            scheduled = true;
            window.requestAnimationFrame(updateHeader);
        }
    }, { passive: true });

    landingHeader.addEventListener('focusin', () => {
        landingHeader.classList.remove('is-scroll-hidden');
    });
}
