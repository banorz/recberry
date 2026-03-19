import sys
import os
import subprocess

def main():
    if len(sys.argv) != 2:
        print("Uso: python release.py <versione> (es. v1.1.0)")
        sys.exit(1)
    
    new_version = sys.argv[1].strip()
    
    if not new_version.startswith('v'):
        print("Avviso: Di solito le versioni dovrebbero iniziare con 'v' (es. v1.1.0)")
        
    # 1. Aggiorna il file version.txt
    version_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.txt")
    with open(version_file, "w") as f:
        f.write(new_version)
    print(f"[OK] Aggiornato version.txt a {new_version}")

    # 2. Esegui i comandi Git
    try:
        subprocess.run(["git", "add", "version.txt"], check=True)
        subprocess.run(["git", "commit", "-m", f"chore: bump version a {new_version}"], check=True)
        subprocess.run(["git", "tag", "-a", new_version, "-m", f"Release {new_version}"], check=True)
        print(f"[OK] Fatto! Versione '{new_version}' salvata (commit) e taggata correttamente nel sistema Git.")
        print(f"\n=> Ora ti basta fare:\n=> git push origin main --tags")
    except subprocess.CalledProcessError as e:
        print(f"[ERRORE] Qualcosa è andato storto con i comandi Git: {e}")
        
    except FileNotFoundError:
        print("[ERRORE] Assicurati di avere Git installato e configurato nel terminale.")

if __name__ == "__main__":
    main()
