// Chaque donnée reste uniquement dans le navigateur de la personne qui l'utilise.
// Rien n'est envoyé à un serveur : c'est ce qui permet de distribuer l'application
// à un grand nombre de studios sans avoir à gérer de base de données ni de comptes.

const PREFIX = "prixel:";

export const storage = {
  async get(key) {
    try {
      const raw = window.localStorage.getItem(PREFIX + key);
      if (raw === null) return null;
      return { key, value: raw, shared: false };
    } catch (e) {
      console.error("Lecture impossible :", e);
      return null;
    }
  },

  async set(key, value) {
    try {
      window.localStorage.setItem(PREFIX + key, value);
      return { key, value, shared: false };
    } catch (e) {
      console.error("Écriture impossible :", e);
      return null;
    }
  },

  async delete(key) {
    const existed = window.localStorage.getItem(PREFIX + key) !== null;
    window.localStorage.removeItem(PREFIX + key);
    return { key, deleted: existed, shared: false };
  },

  async list(prefix = "") {
    const keys = Object.keys(window.localStorage)
      .filter((k) => k.startsWith(PREFIX + prefix))
      .map((k) => k.slice(PREFIX.length));
    return { keys, prefix, shared: false };
  },
};
