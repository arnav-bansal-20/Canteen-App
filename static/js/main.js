// Main JS for Cafeteria Compass

function addToCart(id, name, price) {
    let cart = JSON.parse(sessionStorage.getItem('cart')) || [];
    let item = cart.find(i => i.id == id);
    if (item) {
        item.quantity += 1;
    } else {
        cart.push({ id, name, price: parseFloat(price), quantity: 1 });
    }
    sessionStorage.setItem('cart', JSON.stringify(cart));
    updateCartCount();

    // Visual button feedback
    if (window.event && window.event.target) {
        const btn = window.event.target;
        const originalText = btn.innerText;
        btn.innerText = 'Added! ✓';
        setTimeout(() => { btn.innerText = originalText; }, 900);
    }

    // If sidebar open, update view
    const sidebar = document.getElementById('cartSidebar');
    if (sidebar && sidebar.classList.contains('open') && typeof renderCart === 'function') {
        renderCart();
    }
}

function updateCartCount() {
    let cart = JSON.parse(sessionStorage.getItem('cart')) || [];
    let count = cart.reduce((acc, item) => acc + item.quantity, 0);
    const badges = document.querySelectorAll('.cart-count');
    badges.forEach(badge => {
        badge.innerText = count;
    });
}

document.addEventListener('DOMContentLoaded', () => {
    updateCartCount();
});
