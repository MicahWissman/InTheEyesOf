import { useState, useEffect, useCallback } from 'react';
import { NarrativeViewer } from './components/NarrativeViewer';
import { AudioProvider } from './contexts/AudioContext';
import { AIProvider } from './contexts/AIContext';
import './App.css';

type Lang = 'en' | 'it' | 'es';
type Gender = 'm' | 'f';
const LANGS: { code: Lang; label: string }[] = [
  { code: 'en', label: 'English' },
  { code: 'it', label: 'Italiano' },
  { code: 'es', label: 'Español' },
];
const LS_LANG_KEY = 'eyesof:lang';
const LS_GENDER_KEY = 'eyesof:gender';

interface RecordingConfig {
  id: string;
  lang?: string;
  title: string;
  anchorsFile: string;
  pointCloudFile: string;
  pointCloudLodFile?: string;
  semanticGraphFile?: string;
  trajectoryFile?: string;
}

interface Manifest {
  recordings: RecordingConfig[];
}

function savedLang(): Lang {
  const v = localStorage.getItem(LS_LANG_KEY);
  if (v === 'en' || v === 'es') return v;
  return 'it';
}

function savedGender(): Gender {
  const v = localStorage.getItem(LS_GENDER_KEY);
  if (v === 'm') return v;
  return 'f';
}

function App() {
  const [recordings, setRecordings] = useState<RecordingConfig[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [lang, setLang] = useState<Lang>(savedLang);
  const [gender, setGender] = useState<Gender>(savedGender);
  const [manifestError, setManifestError] = useState(false);
  const [gpsStatus, setGpsStatus] = useState<'waiting' | 'active' | 'error' | 'too_far'>('waiting');
  const handleGpsStatus = useCallback((s: 'waiting' | 'active' | 'error' | 'too_far') => setGpsStatus(s), []);

  const changeLang = useCallback((l: Lang) => {
    setLang(l);
    localStorage.setItem(LS_LANG_KEY, l);
  }, []);

  const changeGender = useCallback((g: Gender) => {
    setGender(g);
    localStorage.setItem(LS_GENDER_KEY, g);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const param = params.get('recording');
    if (param) setSelectedId(param);
  }, []);

  useEffect(() => {
    fetch('/recordings/manifest.json')
      .then(res => res.json())
      .then((data: Manifest) => setRecordings(data.recordings))
      .catch(() => setManifestError(true));
  }, []);

  const handleSelect = (id: string) => {
    setSelectedId(id);
    const url = new URL(window.location.href);
    url.searchParams.set('recording', id);
    window.history.pushState({}, '', url);
  };

  if (manifestError) {
    return (
      <div className="status-screen">
        <p className="status-error">Could not load recordings/manifest.json</p>
        <p className="status-hint">Ensure the file exists in web-viewer/public/recordings/</p>
      </div>
    );
  }

  if (recordings.length === 0) {
    return <div className="status-screen"><p className="status-loading">Loading recordings...</p></div>;
  }

  const selected = recordings.find(r => r.id === selectedId) ?? null;
  const filtered = recordings;

  if (!selected) {
    return (
      <div className="selector-screen">
        <div className="selector-card">
          <h1 className="selector-title">InTheEyesOf</h1>
          <p className="selector-subtitle">Select language</p>
          <div className="lang-picker">
            {LANGS.map(l => (
              <button
                key={l.code}
                className={`lang-btn${lang === l.code ? ' active' : ''}`}
                onClick={() => changeLang(l.code)}
              >
                {l.label}
              </button>
            ))}
          </div>
          {filtered.length > 0 ? (
            <ul className="recording-list">
              {filtered.map(r => (
                <li key={r.id}>
                  <button className="recording-btn" onClick={() => handleSelect(r.id)}>
                    <span className="recording-btn-title">{r.title}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="selector-empty">No recordings available in {LANGS.find(l => l.code === lang)?.label ?? lang} yet.</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <AudioProvider>
    <AIProvider>
      <div className="app-root">
        <div className="recording-switcher">
          <span className="switcher-label">REC</span>
          <select
            className="switcher-select"
            value={selected.id}
            onChange={e => handleSelect(e.target.value)}
          >
            {recordings.map(r => (
              <option key={r.id} value={r.id}>{r.title}</option>
            ))}
          </select>
          {gpsStatus !== 'waiting' && (
            <span className={`switcher-gps ${gpsStatus === 'active' ? 'switcher-gps-active' : gpsStatus === 'too_far' ? 'switcher-gps-toofar' : 'switcher-gps-error'}`}>
              {gpsStatus === 'active' ? '●' : gpsStatus === 'too_far' ? '○' : '✕'}
            </span>
          )}
        </div>
        <NarrativeViewer
          key={selected.id}
          title={selected.title}
          anchorsUrl={`/recordings/${selected.id}/${selected.anchorsFile}`}
          pointCloudUrl={`/recordings/${selected.id}/${selected.pointCloudLodFile ?? selected.pointCloudFile}`}
          semanticGraphUrl={selected.semanticGraphFile ? `/recordings/${selected.id}/${selected.semanticGraphFile}` : undefined}
          trajectoryUrl={selected.trajectoryFile ? `/recordings/${selected.id}/${selected.trajectoryFile}` : undefined}
          onGpsStatusChange={handleGpsStatus}
          lang={lang}
          onLangChange={changeLang}
          gender={gender}
          onGenderChange={changeGender}
        />
      </div>
    </AIProvider>
    </AudioProvider>
  );
}

export default App;
