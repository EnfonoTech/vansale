// Copy-to-clipboard + version stamp wiring.
// Minimal, no framework — served as a plain static asset from Vercel.

(function () {
  // Copy buttons.
  document.querySelectorAll("button.copy").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const value = btn.getAttribute("data-copy");
      if (!value) return;
      try {
        await navigator.clipboard.writeText(value);
      } catch {
        // Fallback for older browsers — select and execCommand is deprecated
        // but still works on Android pre-Chrome-88. Best effort.
        const ta = document.createElement("textarea");
        ta.value = value;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); } catch (_) { /* noop */ }
        document.body.removeChild(ta);
      }
      const old = btn.textContent;
      btn.textContent = "Copied ✓";
      btn.classList.add("copied");
      setTimeout(() => {
        btn.textContent = old;
        btn.classList.remove("copied");
      }, 1400);
    });
  });

  // Scroll-reveal for section headings once in viewport.
  if ("IntersectionObserver" in window && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            e.target.style.transition = "opacity 0.6s ease, transform 0.6s ease";
            e.target.style.opacity = "1";
            e.target.style.transform = "translateY(0)";
            io.unobserve(e.target);
          }
        }
      },
      { threshold: 0.12 },
    );
    document.querySelectorAll(".section-head, .feature-grid li, .steps li, .tour-list li").forEach((el) => {
      el.style.opacity = "0";
      el.style.transform = "translateY(10px)";
      io.observe(el);
    });
  }
})();
