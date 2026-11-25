// Interactions côté navigateur. Aucun appel aux services ici : tout passe par Flask.

document.addEventListener("DOMContentLoaded", () => {
  // --- Menu (affichage mobile) ---
  const menuBtn = document.querySelector("#menu-toggle");
  const menu = document.querySelector("#menu");
  if (menuBtn && menu) {
    menuBtn.addEventListener("click", () => {
      const ouvert = menu.classList.toggle("ouvert");
      menuBtn.setAttribute("aria-expanded", String(ouvert));
    });
  }

  // --- Afficher / masquer un mot de passe ---
  document.querySelectorAll("[data-toggle-password]").forEach((bouton) => {
    const champ = document.querySelector(bouton.dataset.togglePassword);
    if (!champ) return;
    bouton.addEventListener("click", () => {
      const visible = champ.type === "text";
      champ.type = visible ? "password" : "text";
      bouton.textContent = visible ? "Afficher" : "Masquer";
    });
  });

  // --- Inscription : les deux mots de passe doivent correspondre ---
  const formInscription = document.querySelector("#form-inscription");
  if (formInscription) {
    const mdp = formInscription.querySelector("#mdp");
    const mdp2 = formInscription.querySelector("#mdp2");
    const erreur = document.querySelector("#erreur-mdp");

    const verifier = () => {
      const different = mdp2.value !== "" && mdp.value !== mdp2.value;
      if (erreur) erreur.hidden = !different;
      return !different;
    };

    mdp.addEventListener("input", verifier);
    mdp2.addEventListener("input", verifier);
    formInscription.addEventListener("submit", (event) => {
      if (!verifier()) {
        event.preventDefault();
        mdp2.focus();
      }
    });
  }

  // --- Compteur de caractères des zones de texte ---
  document.querySelectorAll("textarea[data-max]").forEach((zone) => {
    const max = Number(zone.dataset.max);
    const compteur = document.querySelector(zone.dataset.compteur);
    const bouton = zone.form ? zone.form.querySelector("button[type='submit']") : null;
    if (!compteur || !max) return;

    const maj = () => {
      const restants = max - zone.value.length;
      compteur.textContent =
        restants >= 0
          ? `${restants} caractère${restants > 1 ? "s" : ""} restant${restants > 1 ? "s" : ""}`
          : `${-restants} caractère${restants < -1 ? "s" : ""} en trop`;
      compteur.classList.toggle("depasse", restants < 0);
      if (bouton) bouton.disabled = restants < 0;
    };

    zone.addEventListener("input", maj);
    maj();
  });

  // --- Les messages de succès disparaissent tout seuls ---
  document.querySelectorAll(".message-success").forEach((message) => {
    setTimeout(() => message.remove(), 5000);
  });
});
