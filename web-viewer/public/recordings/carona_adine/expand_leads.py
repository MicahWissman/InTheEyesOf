#!/usr/bin/env python3
"""Expand 10 lead anchors with deep narratives and mark lead/sub-anchor relationships."""
import json

with open('anchors_route.json') as f:
    data = json.load(f)

candidates = data['candidates']
by_id = {c['node_id']: c for c in candidates}

# ── Lead designations ──────────────────────────────────────────────────────────
LEADS = {
    112: {'score': 0.75, 'title': 'Loreto Square: Stone, Orientation, and Sacred Geography',
          'subs': [105, 110, 116]},
    87:  {'score': 0.65, 'title': 'The Accessible Via Crucis',
          'subs': [85]},
    69:  {'score': 0.78, 'title': "Loreto's Legacy: Heritage, Philosophy, and an Accidental Architect",
          'subs': [71, 135]},
    190: {'score': 0.60, 'title': 'Two Paths: Footprint and Choice',
          'subs': [189]},
    418: {'score': 0.82, 'title': "Sacred Corner: Art, Magnetism, and the Solari Legacy",
          'subs': [411]},
    450: {'score': 0.85, 'title': 'The Altar Line: Marble, Light, and Landscape',
          'subs': [458]},
    502: {'score': 0.80, 'title': 'Santa Marta: Ancestors, Orientation, and the Hidden Foundation',
          'subs': [501, 503]},
    94:  {'score': 0.80, 'title': "Loreto's Artistic and Historical Significance",
          'subs': []},
    24:  {'score': 0.70, 'title': 'The Beech Forest: Underground Cities and Silent Mayors',
          'subs': []},
    1:   {'score': 0.70, 'title': "Water's Path Shapes Life",
          'subs': []},
}

# ── Expanded narratives ────────────────────────────────────────────────────────

NARRATIVES = {
    # ── LEAD 1: Loreto Square (112) ── ~3 min ──────────────────────────────────
    112: {
        'en': (
            "On the other side stands Monte San Giorgio. Remember the town's coat of arms "
            "we saw down below? It looks the way it does because we're right on the point "
            "between two watersheds: the one where we see the lake, and the other.\n\n"
            "Now, they used so many elements of this rock to build because they realized "
            "something: the areas richest in quartz give structures where heat concentrates "
            "better. And where there's strong seasonality, that's decisive — you heat the "
            "house better with fewer fires. Not only that: quartz releases heat slowly and "
            "stores it slowly, so in summer it's cooler and in winter warmer. Here adobe "
            "never existed — quartz did. When we know that the great majority of buildings "
            "were constructed this way, it helps us understand the ancient builders' grasp "
            "of the mountain's mineral composition. They aren't only extraordinary sculptors "
            "— they have a deep, internalized knowledge of what the mountain is made of. "
            "That's why they know exactly which stones to use. And if we were to map the use "
            "of this rock, we'd discover it's concentrated in areas critical to heat "
            "transmission and conservation. From this point you can see two parts of the lake "
            "— Lake Lugano, and the Val Malcantone beyond.\n\n"
            "I told you San Giorgio is important: remember the position, we're south-north, "
            "the north is behind me, the south is here. At midday a light comes through that "
            "window and illuminates San Giorgio and Sant'Andrea: they're not only looking at "
            "the mountain behind us, they'll be lit by that window placed precisely there. "
            "That's why the church was oriented this way — and you begin to grasp how they "
            "thought: every church is a point of view and of relationship, with one another, "
            "with the forest, with the mountain's peak.\n\n"
            "Look: that part over there is Switzerland, and down here runs a wonderful walk. "
            "Further on there's a village called Quasso, al Piano and al Monte: there "
            "Manfredo went to train as a priest, an erudite Milanese of the late twelfth "
            "century. There he came upon the manuscripts of a famous healer-saint, Hildegard "
            "of Bingen, and learned all her plants; then, looking at the mountain, he said: "
            "I want to be a hermit up there — and as he climbed he found the very plants he "
            "had studied, and became the mountain's healer-saint."
        ),
        'it': (
            "Dall'altro lato si trova il Monte San Giorgio. Ricordate lo stemma della città "
            "che abbiamo visto in basso? È fatto così perché noi siamo proprio sulla punta "
            "tra due versanti: quello dove vediamo il lago, e l'altro.\n\n"
            "Ora, hanno usato così tanti elementi di questa roccia per costruire perché se ne "
            "sono accorti: le aree più ricche di quarzo danno strutture in cui il calore si "
            "concentra meglio. E dove c'è molta stagionalità, è decisivo — scaldi meglio la "
            "casa con meno fuochi. Non solo: il quarzo rilascia il calore lentamente e lo "
            "accumula piano, così d'estate è più fresco e d'inverno più caldo. Qui non è mai "
            "esistito l'adobe — è esistito il quarzo. Quando sappiamo che la gran parte degli "
            "edifici è stata costruita così, ci aiuta a capire la comprensione che gli antichi "
            "costruttori avevano della composizione mineralogica della montagna. Non sono solo "
            "ultrascultori — hanno una conoscenza interiorizzata, potente, di cosa è fatta la "
            "montagna. Per questo sanno usare esattamente gli elementi litici che servono. E "
            "se noi mappassimo l'uso di questa roccia, scopriremmo che sta nelle aree critiche "
            "per la trasmissione e la conservazione del calore. Da questo punto si vedono due "
            "parti del lago — il lago di Lugano, e la Val Malcantone.\n\n"
            "Vi ho detto che San Giorgio è importante: ricordate la posizione, siamo sud-nord, "
            "il nord è dietro di me, il sud è qui. A mezzogiorno entra una luce da quella "
            "finestra e illumina San Giorgio e Sant'Andrea: non guardano solo la montagna "
            "dietro di noi, saranno illuminati da quella finestra messa proprio lì. È per "
            "questo che la chiesa è stata orientata così — e capisci come la pensavano: tutte "
            "le chiese sono punti di vista e di relazione, tra loro, con il bosco, con la "
            "punta della montagna.\n\n"
            "Guardate: quella parte di là è Svizzera, e qua sotto passa una passeggiata "
            "stupenda. Più avanti c'è un paese che si chiama Quasso, al Piano e al Monte: lì "
            "andò a studiare da sacerdote Manfredo, un milanese erudito della seconda metà del "
            "Dodicesimo secolo. Là entrò in contatto con i manoscritti di una famosa santa "
            "guaritrice, Ildegarda di Bingen, e ne imparò tutte le piante; poi, guardando la "
            "montagna, disse: voglio essere eremita lassù — e salendo ritrovò proprio le "
            "piante che aveva studiato, e divenne il santo guaritore della montagna."
        ),
    },

    # ── LEAD 2: Via Crucis (87) ── ~2 min ──────────────────────────────────────
    87: {
        'en': (
            "The sacred is coming into contact with something greater than us — that which "
            "builds creation, gives life to everything that surrounds us. And this is made "
            "beautifully: do you see this little old man? Look how lovely he is — there's an "
            "old man climbing, there are young people.\n\n"
            "One of the most beautiful things about this Via Crucis, and I love this so much, "
            "is that it's completely accessible. It's not Everest, reached only by the most "
            "athletic. The little child, the elderly, families, people like you and me — "
            "everyone can discover that something exists beyond the limits of the visible and "
            "the perceivable, in the very short space and time of our lives. To have shaped "
            "this Via Crucis this wide meant that even carts, horses, people who couldn't walk, "
            "even the sick could climb. So the Via Crucis doesn't only mean making a small "
            "effort to ascend and enter a space where you're in contact with what transcends — "
            "it also means giving everyone the possibility to reach a sacred place. And "
            "ancestrally, the sacred places are also those that harbor the greatest number of "
            "medicinal plants. So to be healed in the spirit also means to be healed in the "
            "body."
        ),
        'it': (
            "Il sacro è entrare in contatto con qualcosa di più grande di noi — ciò che "
            "costruisce la creazione, che dà vita a tutto quello che ci circonda. E questo è "
            "fatto benissimo: vedete questo vecchino? Guardate che carino. C'è un vecchino "
            "che sale, ci sono dei ragazzi.\n\n"
            "Una delle cose più belle di questa Via Crucis, e a me piace tantissimo, è che è "
            "totalmente accessibile. Non è l'Everest, dove arriva solo il più atletico. Il "
            "piccolino, l'anziano, le famiglie, persone come voi e me — tutti possono "
            "scoprire che esiste qualcosa che va oltre i limiti del visibile e del percepibile, "
            "nello spazio e nel tempo ridottissimo della nostra vita. Aver sagomato questa Via "
            "Crucis con questa ampiezza significa che riuscivano a salire anche i carri, i "
            "cavalli, magari persone che non camminavano, magari dei malati. Quindi le vie "
            "crucis non indicano solo fare un piccolo sforzo per ascendere ed entrare in uno "
            "spazio dove sei a contatto con ciò che trascende — ma anche dare la possibilità "
            "a chiunque di arrivare in un luogo sacro. E ancestralmente i luoghi sacri sono "
            "anche quelli che ospitano il numero maggiore di piante medicinali. Quindi essere "
            "curati nello spirito significa anche essere curati nel corpo."
        ),
    },

    # ── LEAD 3: Loreto Church (69) ── ~3 min ──────────────────────────────────
    69: {
        'en': (
            "Still in use, like this. Come here — this was in the archive too. I'm not sure "
            "if you noticed it in the floor: it's quite important because it gives us the "
            "cardinal directions — it's an orienter. When there was no compass, there were "
            "these. And so it's here, and it was there. Forgive me for not mentioning it "
            "earlier, but I'll take this chance to tell you now.\n\n"
            "Today's Ticino resembles the French school more than the English one. The "
            "English school says a building is like an old aunt: you give her a cane, you "
            "care for her a little, but you can't stop her from dying — and so English "
            "travelers drew ruins covered in ivy, where you see more ivy than building. The "
            "French school instead says: you must give back the idea of what it was. The "
            "castle's tower is missing? We rebuild it. How? We look for documents — but the "
            "important thing is to redo it. Carcassonne is an entire medieval village with "
            "castle, walls, and everything, completely invented in the 1800s to give the idea "
            "of the Middle Ages. And not far away, Milan's Sforza Castle, built by the very "
            "families who exercised their influence from here: it was in ruins, rebuilt in the "
            "1800s with a tower called the Tower of Filarete — Filarete never built it, they "
            "invented it from drawings. And this gives an idea of how so often these stories "
            "radically transform places.\n\n"
            "At the start of the 1500s the Madonna of Loreto was visited by a group of Polish "
            "princes, captivated by the Italian heritage. They looked for an architect to "
            "explain the house, but there was only the guardian, who'd worked there as a "
            "laborer; to make himself look good he said he was the architect, and explained it "
            "all beautifully. They were thrilled and wanted him to come with them. He, with no "
            "wife, no children, no ties, said 'why not' and set off, pretending to be the "
            "architect. And instead of going directly from Loreto to Poland, they made many "
            "stops, and at each stop they presented him as the great architect — and he "
            "panicked every time, because he wasn't one. But on this very long journey from "
            "Loreto to Krakow, he genuinely became an architect: by looking at monuments, by "
            "engaging with every person he met, without meaning to, by sheer force of thinking "
            "himself an architect, he became one. And when he arrived in Krakow, he was the "
            "architect of Loreto. He built an extraordinary architecture almost identical to "
            "the House of Loreto, and contributed in an epochal way to spreading this typology "
            "across the world."
        ),
        'it': (
            "Ancora in uso, così. Venite qui — questo era anche nell'archivio. Non so se "
            "l'avete notato nel pavimento: è molto importante perché ci dà le direzioni "
            "cardinali — è un orientatore. Quando non c'era la bussola, c'erano queste cose. "
            "Sta qui, e stava là. Scusate se non l'ho detto prima, ma approfitto per "
            "dirvelo adesso.\n\n"
            "Il Ticino di oggi assomiglia più alla scuola francese che a quella inglese. La "
            "scuola inglese dice che un edificio è come una vecchia zia: le dai un bastone, "
            "la curi un po', ma non puoi impedirle di morire — e così i viaggiatori inglesi "
            "disegnavano le rovine coperte d'edera, dove si vede più edera che edificio. La "
            "scuola francese, invece, dice: bisogna restituire l'idea di com'era. Manca la "
            "torre di un castello? La rifacciamo. Come? Cerchiamo dei documenti — ma "
            "l'importante è rifare. Carcassonne è un intero villaggio medievale con castello, "
            "mura e tutto, completamente inventato nell'Ottocento per dare l'idea del "
            "Medioevo. E senza andare troppo lontano, anche il Castello Sforzesco a Milano, "
            "costruito dalle stesse famiglie che esercitavano la loro influenza da qui: era in "
            "rovina, ricostruito nell'Ottocento con una torre che si chiama Torre del Filarete "
            "— Filarete non l'ha mai costruita, se la sono inventata dai disegni. E questo dà "
            "un'idea di come tante volte queste storie trasformano in maniera radicale i "
            "luoghi.\n\n"
            "All'inizio del Cinquecento la Madonna di Loreto fu visitata da un gruppo di "
            "principi polacchi, affascinati dal patrimonio italiano. Cercavano un architetto "
            "che spiegasse la casa, ma c'era solo il guardiano, che vi aveva lavorato come "
            "operaio; per farsi bello disse di essere l'architetto, e spiegò tutto benissimo. "
            "Loro si entusiasmarono e lo vollero con sé. Lui, senza moglie né figli né legami, "
            "disse «perché no» e partì, fingendosi architetto. E invece di andare direttamente "
            "da Loreto in Polonia, fecero moltissime tappe, e a ogni tappa lo presentavano "
            "come il grande architetto — e lui ogni volta nel panico, perché non lo era. Ma in "
            "questo lunghissimo viaggio da Loreto a Cracovia, realmente divenne un architetto: "
            "guardando i monumenti, relazionandosi con tutte le persone, senza volerlo, a "
            "furia di pensare di essere architetto lo diventò. E quando arrivò a Cracovia, era "
            "l'architetto di Loreto. Costruì un'architettura straordinaria quasi identica alla "
            "Casa di Loreto, e contribuì in maniera epocale a diffondere questa tipologia nel "
            "mondo."
        ),
    },

    # ── LEAD 4: The Fork (190) ── ~2 min ──────────────────────────────────────
    190: {
        'en': (
            "On the old path the shrubs can grow, they can do their work; here, with the "
            "passage of carts, they cannot. And there isn't only a spatial fragmentation of "
            "the habitat — there's an acoustic one too: pass a hundred times with an engine "
            "and the little grass no longer grows. Look: there's all the moss there, and none "
            "here — and it isn't a matter of temperature. It's a different human footprint: "
            "there the motorized industrial one, here the natural path.\n\n"
            "I don't know if you can record it, but I hope it comes across — do you see it? "
            "I couldn't have explained this without standing at one first. Each time in your "
            "life, when you see two paths… There's a beautiful poem by Robert Frost — he was "
            "certainly never here, he's an American poet — but it's exactly this image:\n\n"
            "'Two roads diverged in a yellow wood,\n"
            "And sorry I could not travel both…\n"
            "I took the one less traveled by,\n"
            "And that has made all the difference.'\n\n"
            "Before Paul Simon, Frost was someone who knew the woods intimately. And this is "
            "literally it — right here, this fork. Let's go: unfortunately, we return to "
            "civilization."
        ),
        'it': (
            "Nel sentiero antico gli arbusti possono crescere, possono fare il loro lavoro; "
            "qui, con il passaggio dei carri, no. E non c'è solo una frammentazione spaziale "
            "dell'habitat — ce n'è anche una acustica: se passi cento volte con un motore, "
            "l'erbetta non cresce più. Guardate: lì c'è tutto il muschio, e qui no — e non è "
            "una questione di temperatura. È una diversa impronta umana: là l'impronta "
            "industriale motorizzata, qui il sentiero naturale.\n\n"
            "Non so se riuscite a riprenderlo, ma spero si capisca — lo vedete? Non avrei "
            "potuto spiegarlo senza trovarmi davanti a un bivio. Ogni volta nella vita, "
            "quando vedrete due sentieri… C'è una bellissima poesia di Robert Frost — non era "
            "certo qui, è un poeta americano — ma è proprio questa immagine:\n\n"
            "«Two roads diverged in a yellow wood,\n"
            "And sorry I could not travel both…\n"
            "I took the one less traveled by,\n"
            "And that has made all the difference.»\n\n"
            "Prima di Paul Simon, Frost era uno che conosceva i boschi intimamente. E questo "
            "è letteralmente qui — proprio questa biforcazione. Andiamo: purtroppo torniamo "
            "alla civiltà."
        ),
    },

    # ── LEAD 5: Art Corner (418) ── ~4 min ────────────────────────────────────
    418: {
        'en': (
            "There are two other macaws on the facade of Santa Maria del Sasso in Morcote — "
            "I've found three so far. For an Amazonian macaw to reach this far, someone must "
            "have seen it, drawn it, copied it: it's an important question. The decorations "
            "were redone in the 1700s, but the house is far older, because the Solari family "
            "lived here. It's my favorite house, my favorite corner — because here the "
            "combination of human beings, plants, ideas, and symbols is all in order. And if "
            "we teach people how it was, they'll remember it when they go to buy a house or "
            "make a garden.\n\n"
            "Excuse me, may I ask a question? I'm part of a UNESCO chair. We're doing a "
            "circuit to record the most important and significant things about Carona's "
            "heritage, and I was explaining a bit of the Solari family's history — and this "
            "morning when I took the bus, there was a magazine called Lu, and it opened right "
            "to this. I thought maybe it was a sign that I had to come here and meet you.\n\n"
            "I'm an architect and anthropologist. I spoke of the caduceus, of medicinal "
            "plants, of mountains, of the symbolism of health that runs through the "
            "mythographies to today. And I'm a great admirer of the Solari, who built Milan: "
            "by lineage I'm from Milan, even though I'm Swiss. And this place has called so "
            "many artists — why? This week and next week there's a course on the Aprile "
            "family, who were part of all these families, especially as sculptors. And here, "
            "the fountain is by Meret Oppenheim, who lived… this is the Aprile family house.\n\n"
            "We began by measuring the quantity of buildings expressing monumental heritage "
            "dedicated to the sacred, on Monte San Giorgio and on the Arbostora — which "
            "express a particular biodiversity and an uncommon mineralogical richness. And we "
            "discovered that the measure is about a hundred times higher than normal. Normally "
            "we have one sacred building for every two thousand inhabitants in Lombardy, in "
            "the wider Alpine arc every three thousand — and here, every twenty-three. This "
            "means that throughout the history of Christianity, but also of the Celts, of the "
            "Romans, of the Neanderthals — because we have important evidence of Neanderthals "
            "on Monte San Giorgio — someone has felt the need to establish a relationship with "
            "the sacred through a monument, an artistic gesture. And this, we believe, has a "
            "meaning born from the geomorphology, the water's composition, and the "
            "biodiversity. The sacred is born there. And from the relationship with the "
            "heliacal motions. When these things combine in a certain way, someone experiences "
            "the sacred, and that creates the concentration of artists."
        ),
        'it': (
            "Ci sono altri due guacamayo sulla facciata di Santa Maria del Sasso a Morcote — "
            "ne ho trovati tre finora. Perché un'ara amazzonica arrivi fin qui, qualcuno deve "
            "averla vista, disegnata, copiata: è una domanda importante. Le decorazioni furono "
            "rifatte nel Settecento, ma la casa è molto più antica, perché qui vissero i "
            "Solari. È la mia casa preferita, il mio angolo preferito — perché qui la "
            "combinazione di esseri umani, piante, idee e simboli è tutta in ordine. E se "
            "insegniamo alle persone com'era, se ne ricorderanno quando andranno a comprare "
            "casa o a fare un giardino.\n\n"
            "Mi scusi, posso fare una domanda? Faccio parte di una cattedra UNESCO. Stiamo "
            "facendo un circuito per registrare le cose più importanti e significative del "
            "patrimonio di Carona, e stavo spiegando un po' della storia della famiglia Solari "
            "— e stamattina prendendo l'autobus c'era una rivista che si chiama Lu, e si è "
            "aperta proprio su questo. Ho pensato magari è un segnale che dovevo venire qui e "
            "conoscervi.\n\n"
            "Sono architetta e antropologa. Ho parlato del caduceo, delle piante medicinali, "
            "delle montagne, del simbolismo della salute che attraversa le mitografie fino a "
            "oggi. E sono una grande ammiratrice dei Solari, che hanno costruito Milano: "
            "ancestralmente sono di Milano, anche se sono svizzera. E questo luogo ha chiamato "
            "tanti artisti — perché? Questa settimana e la prossima c'è il corso sugli Aprile, "
            "che facevano parte di tutte queste famiglie, soprattutto scultori. E qui la "
            "fontana è di Meret Oppenheim, che ha vissuto… questa è la casa degli Aprile.\n\n"
            "Abbiamo cominciato misurando la quantità di edifici che esprimesse un patrimonio "
            "monumentale dedicato al sacro, sul Monte San Giorgio e sull'Arbostora — che "
            "esprimono una particolare biodiversità e una ricchezza mineralogica non comune. E "
            "abbiamo scoperto che la misura è circa cento volte più alta del normale. "
            "Normalmente abbiamo un edificio sacro ogni duemila abitanti in Lombardia, "
            "nell'arco alpino ogni tremila — e qui ogni ventitré. Questo vuol dire che durante "
            "la storia della cristianità, ma anche dei Celti, dei Romani, dei Neandertal — "
            "perché abbiamo importanti evidenze neandertal sul Monte San Giorgio — qualcuno "
            "ha sentito la necessità di stabilire una relazione con il sacro attraverso un "
            "monumento, un gesto artistico. E questo, secondo noi, ha un significato che nasce "
            "dalla geomorfologia, dalla composizione dell'acqua e dalla biodiversità. Il sacro "
            "nasce lì. E dalla relazione con i moti eliaci. Quando queste cose si combinano "
            "in un certo modo, qualcuno fa esperienza del sacro — e questo crea la "
            "concentrazione degli artisti."
        ),
    },

    # ── LEAD 6: Church/Altar (450) ── ~3 min ──────────────────────────────────
    450: {
        'en': (
            "Let's read the inscription: 'the holiness of your house prevails.' Lord, grant "
            "us the holiness of your house, says the first line. And then, through the "
            "prayers: 'domus mea' — the house becomes mine; thanks to the prayers, this "
            "house will become mine.\n\n"
            "That line practically pierces the altar and goes toward the mountain: if I draw "
            "it from that corner and let it out there, it arrives exactly before the peak. "
            "San Giorgio is placed looking at himself in the mountain — incredible, isn't it? "
            "And then this 'prosciutto' returns — the marble of Arzo. You'll begin to see it "
            "all around: the different elements composing these churches. You won't find this "
            "stone in many churches outside of here; when you do, it's in very specific "
            "elements of monumental cathedral altars, because it was sold at an incredible "
            "price. Look: the black part isn't marble — all the rest is Arzo marble. In "
            "miniature, this is identical to what you'll find in San Lorenzo: the idea of "
            "maximum marble composition reflecting a maximum organization of the plastic "
            "space.\n\n"
            "In the morning, when the sun comes through that window, this part is strongly "
            "lit and the other stays dark — because the lower part, especially, is the part "
            "of the damned. So the illumination of this church, for the diversity of its "
            "painted compositions, depends on the opening of the windows. That part will "
            "always be in shadow.\n\n"
            "And here it gets extraordinarily interesting: on the counter-facade they've "
            "painted a Last Supper, interpreted — because behind the Last Supper is the "
            "landscape that surrounds us. Leonardo places an abstract space, a conceptual "
            "place; but here the artist has set this scene in a real place, and behind it "
            "is Monte San Giorgio, once again.\n\n"
            "I wanted to end our path here because it seems incredible: a church of the "
            "sixteenth and seventeenth centuries, these are architectures that are ultra "
            "self-referential — they have twelve hundred years of history before them, they "
            "need nothing to build themselves. And yet, even after so many centuries, this "
            "church continues to speak with the landscape. And this means that the persistence "
            "and the dialogue with nature — the definition of a biocultural heritage — is "
            "still part of a Renaissance moment that we mistakenly attribute only to the "
            "human, where we say the center of interest is the artwork, the human being. "
            "But no: look how they define the elements of nature. And for me, that's a great "
            "lesson."
        ),
        'it': (
            "Leggiamo l'iscrizione: «la santità della tua casa domina». Signore, concedici "
            "la santità della tua casa, dice la prima frase. E poi, con le preghiere: «domus "
            "mea» — la casa diventa mia; grazie alle orazioni, questa casa diventerà mia.\n\n"
            "Quella linea praticamente perfora l'altare e va verso la montagna: se la traccio "
            "da quell'angolo e la faccio uscire di là, arriva esattamente davanti al monte. "
            "San Giorgio è posizionato guardando se stesso nella montagna — incredibile, no? "
            "E poi si ripete questo «prosciutto» — il marmo di Arzo. Comincerete a rivederlo "
            "tutt'intorno: i diversi elementi che compongono queste chiese. Non troverete "
            "questa pietra in molte chiese fuori da qui; la trovate per elementi molto "
            "specifici di altari monumentali di cattedrali, perché era venduto a un prezzo "
            "incredibile. Guardate: la parte nera non è marmo — tutto il resto è marmo di "
            "Arzo. Questo in miniatura è identico a quello che troverete in San Lorenzo: "
            "l'idea della massima composizione dei marmi che si riflette in una massima "
            "organizzazione dello spazio plastico.\n\n"
            "Alla mattina, quando il sole entra da quella finestra, questa parte è molto "
            "illuminata e questa resta oscura — perché la parte inferiore, soprattutto, è la "
            "parte dei dannati. Quindi l'illuminazione di questa chiesa, per la diversità "
            "delle composizioni dipinte, dipende dall'apertura delle finestre. Quella parte "
            "sarà sempre in ombra.\n\n"
            "E qua è super interessante: nella controfacciata hanno fatto un'Ultima Cena, "
            "interpretata — perché dietro l'Ultima Cena c'è il paesaggio che ci circonda. "
            "Leonardo pone uno spazio astratto, un luogo concettuale; ma qui l'artista ha "
            "definito la scena in un luogo reale, e dietro c'è il Monte San Giorgio, ancora "
            "una volta.\n\n"
            "Volevo finire il nostro percorso qui perché mi sembra incredibile: una chiesa "
            "del Cinquecento e del Seicento, architetture ultra autoreferenziate — hanno "
            "milleduecento anni di storia prima, non hanno bisogno di niente per costruirsi. "
            "Eppure, persino dopo tanti secoli, questa chiesa continua a parlare con il "
            "paesaggio. E questo vuol dire che la persistenza e il dialogo con la natura — "
            "la definizione di un patrimonio bioculturale — è ancora parte di un momento "
            "rinascimentale che noi erroneamente attribuiamo solo all'essere umano, in cui "
            "diciamo che il centro dell'interesse è l'opera artistica, l'essere umano. E "
            "invece no: guardate come loro definiscono gli elementi della natura. E questo "
            "per me è un grande insegnamento."
        ),
    },

    # ── LEAD 7: Santa Marta (502) ── ~3 min ───────────────────────────────────
    502: {
        'en': (
            "Here there's a church that fascinates me. The first thing you'll notice is that "
            "the cemetery is in front — in ninety-five percent of Catholic churches on the "
            "planet, the cemetery is behind. When the cemetery is in front, something is "
            "happening: the ancestors are placed in contact with something more important "
            "than the normal orientation. This disposition of the dead in front of the temple "
            "is very typical of the Celts — the warriors defending the sacred space. The "
            "Christians came and said, look, those ancestors were already here, we'll explain "
            "them with our narrative. It's an integration: gentle, respectful, progressive.\n\n"
            "Now look at the orientation between the peak of the mountain and the roof of the "
            "cemetery and this church. You see? It's almost noon. I have a little app that "
            "lets me simulate the sun's orientation by the hour — it rose behind that mountain, "
            "went up like this, and at one o'clock, which is solar noon because we're on legal "
            "time, it will be exactly at the peak. The people who built this church, who put "
            "the door here, who oriented it here, who placed their ancestors in front — they "
            "put it facing the most sacred thing, exactly south, facing the mountain. They "
            "knew that orienting sacred spaces connected you to what transcends.\n\n"
            "And look where the floor is — see the windows? All of that is a base platform. "
            "No one in the world needs to build a foundation that high for a building this "
            "size. They could have perfectly well built on the ground. If they didn't, it's "
            "because in that rock, inside what they're encapsulating, there must be something "
            "more — perhaps an altar or an area already levelled, already used. They placed "
            "themselves on top. It can't be empty in there. What they've done is surely "
            "encapsulate something — there's no archaeological project here, but the "
            "architecture itself reveals that something inside justifies the exaggerated "
            "height of the church."
        ),
        'it': (
            "C'è una chiesa qui che mi affascina. La prima cosa che noterete è che il cimitero "
            "è davanti — nel novantacinque per cento delle chiese cattoliche del pianeta, il "
            "cimitero è dietro. Quando il cimitero è davanti, succede qualcosa: gli antenati "
            "sono messi a contatto con qualcosa di più importante dell'orientamento normale. "
            "Questa disposizione dei morti davanti al tempio è molto tipica dei Celti — i "
            "guerrieri che difendono lo spazio sacro. I cristiani sono arrivati e hanno detto: "
            "guardate, quegli antenati erano già qui, li spieghiamo con la nostra narrativa. "
            "È un'integrazione: dolce, rispettosa, progressiva.\n\n"
            "Ora guardate l'orientamento tra la punta della montagna e il tetto del cimitero "
            "e questa chiesa. Lo vedete? È quasi mezzogiorno. Ho una piccola app che mi "
            "permette di simulare l'orientamento del sole per ora — è salito dietro quella "
            "montagna, è andato così, e all'una, che sarà il mezzogiorno solare perché siamo "
            "con l'ora legale, sarà esattamente alla punta. La gente che ha costruito questa "
            "chiesa, che ha messo la porta qui, che l'ha orientata qui, che ha messo davanti "
            "gli antenati — l'ha messa davanti alla cosa più sacra, esattamente a sud, di "
            "fronte alla montagna. Loro sapevano che orientare gli spazi sacri ti metteva in "
            "connessione con ciò che trascende.\n\n"
            "E guardate dov'è il pavimento — vedete le finestre? Tutto quello è un basamento. "
            "Nessuno al mondo ha bisogno di costruire un basamento di quell'altezza per un "
            "edificio di queste dimensioni. Avrebbero potuto tranquillamente costruire a "
            "livello del suolo. Se non l'hanno fatto, è perché in quella roccia, dentro quello "
            "che stanno incapsulando, deve esserci qualcosa di più — forse un altare o una "
            "zona già livellata, già utilizzata. Si sono messi sopra. Non può essere vuoto "
            "lì dentro. Quello che hanno fatto è sicuramente incapsulare qualcosa — non c'è "
            "un progetto archeologico qui, ma l'architettura stessa rivela che qualcosa dentro "
            "giustifica l'altezza esagerata della chiesa."
        ),
    },

    # ── LEAD 8: Loreto Significance (94) ── ~4 min ────────────────────────────
    94: {
        'en': (
            "Why is there a house here? Because it was carried by the angels: it's the House "
            "of Loreto, and 'Ongaro' comes from 'angel,' a sixteenth-century dialect form. "
            "The shape of the mountain itself decided its position, and let this story born "
            "at Loreto come alive here — because the natural characteristics allowed it.\n\n"
            "Then we meet my favorite stone: the marble of Arzo — that prosciutto-like stone "
            "full of fossils. Born where the rock splits on Monte San Giorgio, it's the most "
            "polychrome and most difficult marble to work on the planet. Look at it: the "
            "diversity of colors corresponds to a diversity of mineral composition. If you "
            "strike hard, you might manage to cut this part, but you disintegrate that one. "
            "So whoever can make even this simple balustrade — which for a homogeneous marble "
            "would be easy — is already a wizard. And whoever can make these little columns "
            "is a master. These masters became the maestri comacini, became the incredible "
            "sculptors of this region, became the stucco workers. Look at these gestures — "
            "an artistic expression of someone who knows the working of stone and of three-"
            "dimensional matter like few others. These are the artists called to Rome to build "
            "the statues and stuccos of Roman churches. On Monte San Giorgio there's a village "
            "called Vigiu, with about two hundred inhabitants — in the 1600s, three hundred "
            "people from Vigiu, more than the village could contain, lived in Rome in a "
            "quarter of their own, making all the statues for all the churches of Rome.\n\n"
            "And then there was Carlo Borromeo, who lived in the 1500s and is very important "
            "for these mountains. He was part of the Counter-Reformation: he invented the "
            "hall church, where one person speaks and the others listen. And he did something "
            "else that was crucial — during the Counter-Reformation, with the clear risk of "
            "Protestant expansion, he took all the processions that were on the mountains "
            "and brought them down into the villages, so that even children and the elderly "
            "could see the presence of Catholicism. But the mountains had been left bare — "
            "so to restore them he created the Sacri Monti.\n\n"
            "Now, San Giorgio was placed on a surface we call the counter-facade. It's very "
            "important where he looks: he's looking this way. If I make a hole behind this "
            "beautiful image, behind it is Monte San Giorgio. He was set on axis — the church "
            "was set on axis. From this balustrade you can just glimpse the other lake, but "
            "essentially this orientation is looking at the mountain. What does this mean? "
            "Many things. First: perhaps before this, there was something here that already "
            "looked at the mountain. And the Christian narrative integrated this idea. Perhaps "
            "a platform, perhaps an altar, perhaps a temple already oriented on this mountain. "
            "They built the church but didn't deny this orientation — because the movement of "
            "the celestial bodies is always the same. You can change whatever you like, you "
            "can erase the paths, but the celestial bodies continue to rise in the same place "
            "and set in the same place, according to a pattern that repeats annually."
        ),
        'it': (
            "Perché qui c'è una casa? Perché fu portata dagli angeli: è la Casa di Loreto, "
            "e «Ongaro» viene da «angelo», una forma dialettale del Cinquecento. La forma "
            "stessa della montagna ne ha deciso la posizione, e ha fatto vivere qui questa "
            "storia nata a Loreto — perché le caratteristiche naturali lo permettevano.\n\n"
            "Poi incontriamo la mia pietra preferita: il marmo di Arzo — questa specie di "
            "prosciutto pieno di fossili. Nato dove la roccia si spacca sul Monte San Giorgio, "
            "è il marmo più policromo e più difficile da lavorare del pianeta. Guardatelo: la "
            "diversità dei colori corrisponde a una diversità della composizione minerale. Se "
            "dai un colpo forte, magari riesci a tagliare questa parte, ma disintegri quella. "
            "Quindi chi è in grado di fare anche solo questa balaustra semplice — che per un "
            "marmo omogeneo sarebbe facilissima — è già un mago. E chi riesce a fare queste "
            "colonnine è un maestro. Questi maestri diventano i maestri comacini, gli "
            "scultori incredibili di questa zona, i gessisti. Guardate questi gesti — "
            "un'espressione artistica di chi conosce la lavorazione della pietra e della "
            "materia tridimensionale come pochi. Sono questi gli artisti chiamati a Roma a "
            "costruire le statue e i gessi delle chiese romane. Sul Monte San Giorgio c'è un "
            "villaggio che si chiama Vigiu, con circa duecento abitanti — nel Seicento "
            "trecento vigiutesi, più di quanti il villaggio potesse contenere, abitavano a "
            "Roma in un quartiere tutto loro, facendo tutte le statue di tutte le chiese di "
            "Roma.\n\n"
            "E poi c'è Carlo Borromeo, che visse nel Cinquecento ed è molto importante per "
            "queste montagne. Faceva parte della Controriforma: inventò le chiese ad aula, "
            "dove c'è uno che parla e gli altri che ascoltano. E fece un'altra cosa "
            "importantissima — durante la Controriforma, con il chiarissimo rischio "
            "dell'espansione del pensiero protestante, prese tutte le processioni che stavano "
            "sulle montagne e le portò giù nei villaggi, perché anche bambini e anziani "
            "vedessero la presenza del cattolicesimo. Ma le montagne erano rimaste un po' "
            "spogliate — e quindi per risarcirle creò i Sacri Monti.\n\n"
            "Ora, San Giorgio è stato posizionato sulla controfacciata. È molto importante "
            "dove guarda: sta guardando di qua. Se faccio un buco dietro questa immagine, "
            "dietro c'è il Monte San Giorgio. È stato messo in asse — la chiesa è stata messa "
            "in asse. Da questa balaustra si intravede un po' dell'altro lago, ma "
            "essenzialmente quest'orientamento guarda la montagna. Cosa vuol dire? Tante cose. "
            "Primo: forse qui prima c'era qualcosa che già guardava la montagna. E la "
            "narrativa cristiana ha integrato quest'idea. Magari c'era una piattaforma, un "
            "altare, un tempio già orientato su questa montagna. Hanno costruito la chiesa ma "
            "non hanno negato quest'orientamento — perché il movimento dei corpi celesti è "
            "sempre lo stesso. Puoi cambiare quello che ti pare, puoi cancellare i sentieri, "
            "ma i corpi celesti continuano a sorgere e tramontare nello stesso posto, secondo "
            "uno schema che si ripete annualmente."
        ),
    },

    # ── LEAD 9: Beech Forest (24) ── ~3 min ───────────────────────────────────
    24: {
        'en': (
            "Look: these are the beeches, and the darker, rougher ones are the chestnuts. "
            "They determine the network underneath, and the competition between them comes "
            "from the fact that each has its own idea of how the forest works. Beneath us "
            "the roots are all connected through the mycelium — the network of fungi — and "
            "it's the oldest trees that decide how the minerals and nourishment are shared. "
            "That's why, at the dawn of the relationship between humans and woods, they were "
            "venerated: cut one down and you lose the mayor, the one who organizes everything "
            "below. This is the city, and that is its mayor.\n\n"
            "We walk on only a very thin slice of forest. The forest is far above us and far "
            "below us — we're like a bit of a sandwich, on a surface where what happens below "
            "is as important as what happens above. The amount of humus tells you how many "
            "beings have lived here: how many trees, how many animals, how many vegetable "
            "ancestors of these creatures are underneath. And the mycelium uses all of this "
            "to move nourishment, shifting it here and there. And since the oldest living "
            "things have more authority, they decide. We're walking here on a network far "
            "more complicated than the London Underground.\n\n"
            "And this air, this space you see — it's a classic of beech forests. Beeches are "
            "like people who say: don't touch me too much. They're lovely to look at, but "
            "don't stand too close. They never stand too close to each other — see, there's "
            "one there, another over there. They want space, and they defend it chemically: "
            "they don't allow too many plants to grow attached to them. The chestnut, on the "
            "other hand, is more popular — gets along with everyone, more friendly. And from "
            "the composition of all of them comes the unique character of the forest.\n\n"
            "And we know nothing of this. We live in concrete boxes and we don't know anything "
            "anymore. That's why it's so hard for us to understand environmental conservation. "
            "And yet they're here, working all day long for us, for free, making the water we "
            "drink — and we don't even say thank you."
        ),
        'it': (
            "Guardate: questi sono i faggi, e quelli più scuri e rugosi sono i castagni. "
            "Loro determinano la rete sottostante, e la competizione tra di loro viene dal "
            "fatto che ciascuno ha la sua idea di come funziona il bosco. Sotto di noi le "
            "radici sono tutte collegate attraverso il micelio — la rete di funghi — e sono "
            "gli alberi più anziani a decidere come si distribuiscono i minerali e il "
            "nutrimento. Per questo, all'inizio del rapporto tra uomo e bosco, venivano "
            "venerati: se ne tagli uno, viene a mancare il sindaco, colui che organizza tutto "
            "là sotto. Questa è la città, e quello è il suo sindaco.\n\n"
            "Noi camminiamo su un pezzettino molto sottile di foresta. La foresta è molto "
            "sopra di noi e molto sotto di noi — siamo come un pezzettino di un sandwich, "
            "su una superficie dove tanto importante è quello che succede in basso come "
            "quello che succede in alto. La quantità di humus ci dice quanta gente è vissuta "
            "qui: quanti alberi, quanti animali, quanti antenati vegetali di queste creature "
            "sono sotto. E il micelio usa tutto questo per muovere gli alimenti, spostarli di "
            "qua e di là. E siccome i viventi più antichi hanno più autorità, loro decidono. "
            "Noi stiamo camminando su una rete molto più complicata della metropolitana di "
            "Londra.\n\n"
            "E quest'aria, questo spazio che vedete, è un classico delle faggete. I faggi "
            "sono come quelle persone che dicono: non mi toccare troppo. Sono carini da "
            "guardare, ma non stare troppo vicino. Non stanno mai troppo vicini — vedete, "
            "ce n'è uno lì, poi un altro di là. Desiderano spazio, e lo difendono "
            "chimicamente: non permettono a troppe piante di crescere attaccate a loro. Il "
            "castagno invece è uno più popolare — va bene con tutti, è più amico. E dalla "
            "composizione di tutti viene fuori il carattere unico del bosco.\n\n"
            "E noi di questo non sappiamo niente. Viviamo in scatole di concreto e non "
            "sappiamo più niente. È per questo che è così difficile per noi capire la "
            "conservazione dell'ambiente. Eppure loro sono qui, lavorando tutto il giorno per "
            "noi, gratis, facendo l'acqua che noi beviamo — e noi non diciamo neanche grazie."
        ),
    },

    # ── LEAD 10: Water's Path (1) ── ~2 min ───────────────────────────────────
    1: {
        'en': (
            "The identity and the strength of a place come from the shape of the mountain, "
            "and the shape of the mountain decides how the water falls. See that hollow "
            "descending? It's the product of the mountain shaping itself through the fall of "
            "the water; and from the combination of the water and the mountain's form is born "
            "the very plan of the forest, from which all life rises and activates. If you "
            "don't remember where the water comes from, you can't even build a village, you "
            "won't even have water.\n\n"
            "So what do we see? A hollow, a fall. And that has been recognized, understood, "
            "and codified through a fountain. And in ancient times there are always beings "
            "and figures associated with this — come here, the fountain has two figures, and "
            "from them the water flows. The forest is something alive, not only through the "
            "combination of water and mineral elements that produce all life and all the "
            "forest, but in the very first representations of life. That's a crucial point, "
            "and those representations persist across the centuries. This fountain isn't that "
            "old, but it holds an ancestral way of looking at how it all began.\n\n"
            "So the first mapping when you walk in a forest is: where is the water? We call "
            "it hydrography, we give it all the names in the world, but really it's the path "
            "of the water — which determines the shape of the forest and the path of human "
            "life too. That's the first map our eyes must follow. And besides, it isn't even "
            "the soil we see: what we call humus is really dead beings — trees that have died. "
            "We're walking on top of the trees, on what remains of the cemetery of the trees."
        ),
        'it': (
            "L'identità e la forza di un luogo vengono dalla forma della montagna, e la "
            "forma della montagna decide come cade l'acqua. Vedete quell'avvallamento che "
            "scende? È il prodotto della montagna che si modella grazie alla caduta dell'acqua; "
            "e dalla combinazione tra l'acqua e la forma del monte nasce la pianta stessa del "
            "bosco, da cui tutta la vita si leva e si attiva. Se non ricordi da dove viene "
            "l'acqua, non puoi nemmeno costruire un villaggio, non avrai nemmeno acqua.\n\n"
            "Cosa vediamo, allora? Un avvallamento, una caduta. E questo è stato riconosciuto, "
            "capito e codificato attraverso una fontana. E nell'antichità ci sono sempre "
            "esseri e personaggi associati a questo — venite qui, la fontana ha due personaggi, "
            "e da loro esce l'acqua. Il bosco è qualcosa di vivo, non solo per la combinazione "
            "tra acqua e elementi minerali che producono tutta la vita e tutto il bosco, ma "
            "nelle primissime rappresentazioni della vita stessa. È un punto importantissimo, "
            "e quelle rappresentazioni si mantengono lungo i secoli. Questa fontana non è "
            "così antica, ma tiene una forma ancestrale di guardare a come tutto è nato.\n\n"
            "Quindi il primo mappare quando cammini in un bosco è: dov'è l'acqua? Lo "
            "chiamiamo idrografia, gli diamo tutti i nomi del mondo, ma realmente è il "
            "cammino dell'acqua — che determina la forma del bosco e il cammino della vita "
            "umana. Quella è la prima mappa dei nostri occhi, deve andare con quello. E poi, "
            "non è nemmeno la terra quella che vediamo: quello che chiamiamo humus sono "
            "davvero esseri morti — alberi che sono morti. Stiamo camminando sopra gli alberi, "
            "su quello che resta del cimitero degli alberi."
        ),
    },
}

# ── Apply changes ──────────────────────────────────────────────────────────────

# Mark leads and set expanded narratives
for nid, cfg in LEADS.items():
    c = by_id[nid]
    c['isLead'] = True
    c['score'] = cfg['score']
    c['title'] = cfg['title']
    c['narrative'] = NARRATIVES[nid]

# Mark sub-anchors
for lead_id, cfg in LEADS.items():
    for sub_id in cfg['subs']:
        by_id[sub_id]['leadId'] = lead_id

# Update count
data['count'] = len(candidates)

with open('anchors_route.json', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

# ── Report ─────────────────────────────────────────────────────────────────────
leads = [c for c in candidates if c.get('isLead')]
subs = [c for c in candidates if c.get('leadId')]
print(f"Done: {len(leads)} leads, {len(subs)} sub-anchors, {len(candidates) - len(leads) - len(subs)} solo quick")
print()
for c in sorted(leads, key=lambda x: -x['score']):
    nid = c['node_id']
    en_len = len(c['narrative']['en'])
    it_len = len(c['narrative']['it'])
    est_min = en_len / 750
    print(f"  {nid:>4} | {c['score']:.2f} | en:{en_len:>4} it:{it_len:>4} | ~{est_min:.1f}min | {c['title'][:55]}")
