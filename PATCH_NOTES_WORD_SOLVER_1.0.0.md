# Word Solver Patch 1.0.0

Patch autonome et isofonctionnel du solveur exact-partiel d'equations de mots.

## Portee

Ce patch ne modifie que :

- `src/formal_disk4/words/exact_partial.py` ;
- `tests/test_exact_partial.py`.

Il ne modifie pas :

- la signature publique de `ExactPartialWordSolver` ;
- les limites ou statuts du solveur ;
- les checkpoints ;
- le runner ;
- les LP ;
- l'enumeration ou le quotientage par symetrie ;
- la version globale du projet.

Le fichier d'origine du solveur est identique dans les versions projet 1.5.0, 1.5.1 et 1.6.0. Ce patch peut donc etre applique avant ou apres les patchs 1.5.1 et 1.6.0.

## Optimisations internes

- remplacement des arbres symboliques recopies et serialises par une arene locale hash-consee d'identifiants entiers ;
- suppression de `repr()` dans les signatures d'etats ;
- comptage O(1) de la taille des environnements symboliques ;
- partage structurel des sous-expressions et memoisation des substitutions ;
- signatures canoniques compactes des residus ;
- simplification lineaire des longs prefixes et suffixes communs ;
- substitution specialisee qui reutilise les litteraux non modifies ;
- suppression des copies de chemins DFS a chaque appel recursif ;
- suppression des listes temporaires inutiles dans la canonicalisation.

Aucune contrainte de longueur intermediaire n'est ajoutee dans ce patch. Cela demanderait de modifier le contrat avec le LP et fera l'objet d'un travail separe.

## Validation

- 100 systemes aleatoires deterministes compares bit a bit avec l'ancienne implementation : memes familles, traces, statuts, compteurs et composants non pris en charge ;
- suite projet 1.5.0 apres application : 91 tests passes ;
- suite projet 1.6.0 apres application : 103 tests et 12 sous-tests passes ;
- cas pathologique a 500 etats : 9,42 s avant contre environ 1,0 a 1,2 s apres sur l'environnement de test, avec exactement 500 etats et 1 492 aretes dans les deux versions ;
- corpus aleatoire de 100 petits systemes : 7,13 s avant contre 5,18 s apres sur l'environnement de test.

Les temps sont indicatifs et dependent de la machine et des systemes rencontres.

## Installation

Extraire l'archive a la racine du projet en autorisant l'ecrasement des fichiers existants.

Le hash SHA-256 attendu du fichier source avant application est :

`25a350a50e485cd4739146e43b2f1565c6a583d4de29b9ed8897ff400527ba82`
