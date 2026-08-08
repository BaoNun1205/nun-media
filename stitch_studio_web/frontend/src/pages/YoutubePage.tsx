import { useEffect, useState } from 'react';
import { Plus, Trash2, Link as LinkIcon, Edit3, Youtube, Save, X, Copy, ExternalLink, Eye, Check } from 'lucide-react';
import { studioApi } from '../services/api';
import type { YoutubeChannel, YoutubePrompt, YoutubeReference } from '../types/studio';

export function YoutubePage() {
  const [channels, setChannels] = useState<YoutubeChannel[]>([]);
  const [activeChannelId, setActiveChannelId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<'prompts' | 'references'>('prompts');
  const [prompts, setPrompts] = useState<YoutubePrompt[]>([]);
  
  const [isCreatingChannel, setIsCreatingChannel] = useState(false);
  const [newChannelName, setNewChannelName] = useState('');
  
  const [isEditingPrompt, setIsEditingPrompt] = useState(false);
  const [promptForm, setPromptForm] = useState<{ id?: number; name: string; content: string }>({
    name: '',
    content: '',
  });

  const [channelRefs, setChannelRefs] = useState<YoutubeReference[]>([]);
  const [isEditingRef, setIsEditingRef] = useState(false);
  const [newRefUrl, setNewRefUrl] = useState('');
  const [isSavingRefs, setIsSavingRefs] = useState(false);

  const [viewingPrompt, setViewingPrompt] = useState<YoutubePrompt | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  async function loadChannels() {
    try {
      const data = await studioApi.youtube.channels();
      setChannels(data);
      if (data.length > 0 && !activeChannelId) {
        setActiveChannelId(data[0].id);
      }
    } catch (error) {
      console.error('Failed to load channels', error);
    }
  }

  async function loadPrompts(channelId: number) {
    try {
      const data = await studioApi.youtube.prompts(channelId);
      setPrompts(data);
    } catch (error) {
      console.error('Failed to load prompts', error);
    }
  }

  useEffect(() => {
    loadChannels();
  }, []);

  useEffect(() => {
    if (activeChannelId) {
      loadPrompts(activeChannelId);
      setIsEditingPrompt(false);
      setIsEditingRef(false);
      const channel = channels.find(c => c.id === activeChannelId);
      if (channel) {
        try {
          setChannelRefs(JSON.parse(channel.references_json || '[]'));
        } catch (e) {
          setChannelRefs([]);
        }
      }
    }
  }, [activeChannelId, channels]);

  async function handleCreateChannel(e: React.FormEvent) {
    e.preventDefault();
    if (!newChannelName.trim()) return;
    try {
      const newChannel = await studioApi.youtube.createChannel(newChannelName.trim());
      setChannels([newChannel, ...channels]);
      setActiveChannelId(newChannel.id);
      setNewChannelName('');
      setIsCreatingChannel(false);
    } catch (error) {
      console.error('Failed to create channel', error);
    }
  }

  async function handleDeleteChannel(id: number) {
    if (!window.confirm('Are you sure you want to delete this channel and all its prompts?')) return;
    try {
      await studioApi.youtube.deleteChannel(id);
      setChannels(channels.filter(c => c.id !== id));
      if (activeChannelId === id) {
        setActiveChannelId(channels.length > 1 ? channels.filter(c => c.id !== id)[0].id : null);
      }
    } catch (error) {
      console.error('Failed to delete channel', error);
    }
  }

  async function handleSavePrompt(e: React.FormEvent) {
    e.preventDefault();
    if (!activeChannelId || !promptForm.name.trim() || !promptForm.content.trim()) return;
    try {
      if (promptForm.id) {
        const updated = await studioApi.youtube.updatePrompt(promptForm.id, promptForm.name, promptForm.content);
        setPrompts(prompts.map(p => p.id === updated.id ? updated : p));
      } else {
        const created = await studioApi.youtube.createPrompt(activeChannelId, promptForm.name, promptForm.content);
        setPrompts([created, ...prompts]);
      }
      setIsEditingPrompt(false);
    } catch (error) {
      console.error('Failed to save prompt', error);
    }
  }

  async function handleDeletePrompt(id: number) {
    if (!window.confirm('Delete this prompt?')) return;
    try {
      await studioApi.youtube.deletePrompt(id);
      setPrompts(prompts.filter(p => p.id !== id));
    } catch (error) {
      console.error('Failed to delete prompt', error);
    }
  }

  async function handleAddRef(e: React.FormEvent) {
    e.preventDefault();
    if (!activeChannelId || !newRefUrl.trim()) return;
    setIsSavingRefs(true);
    try {
      const newRefs = [{ url: newRefUrl.trim() }, ...channelRefs];
      const refJson = JSON.stringify(newRefs);
      const updated = await studioApi.youtube.updateChannel(activeChannelId, undefined, refJson);
      setChannels(channels.map(c => c.id === updated.id ? updated : c));
      setNewRefUrl('');
      setIsEditingRef(false);
    } catch (error) {
      console.error('Failed to add reference', error);
      alert('Failed to add reference');
    } finally {
      setIsSavingRefs(false);
    }
  }

  async function handleDeleteRef(index: number) {
    if (!activeChannelId || !window.confirm('Delete this link?')) return;
    try {
      const newRefs = channelRefs.filter((_, i) => i !== index);
      const refJson = JSON.stringify(newRefs);
      const updated = await studioApi.youtube.updateChannel(activeChannelId, undefined, refJson);
      setChannels(channels.map(c => c.id === updated.id ? updated : c));
    } catch (error) {
      console.error('Failed to delete reference', error);
      alert('Failed to delete reference');
    }
  }

  function copyToClipboard(text: string, id: string) {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => {
      setCopiedId(current => current === id ? null : current);
    }, 2000);
  }

  const activeChannel = channels.find(c => c.id === activeChannelId);

  return (
    <section className="page youtube-page">
      <div className="youtube-layout">
        <aside className="youtube-sidebar">
          <div className="sidebar-header">
            <h2>Channels</h2>
            <button className="icon-button" onClick={() => setIsCreatingChannel(true)} title="New Channel">
              <Plus size={18} />
            </button>
          </div>
          
          {isCreatingChannel && (
            <form className="channel-create-form" onSubmit={handleCreateChannel}>
              <input 
                autoFocus
                placeholder="Channel name..." 
                value={newChannelName}
                onChange={e => setNewChannelName(e.target.value)}
              />
              <div className="form-actions">
                <button type="button" className="quiet" onClick={() => setIsCreatingChannel(false)}>Cancel</button>
                <button type="submit" className="primary" disabled={!newChannelName.trim()}>Add</button>
              </div>
            </form>
          )}

          <div className="channel-list">
            {channels.map(channel => (
              <div 
                key={channel.id} 
                className={`channel-item ${activeChannelId === channel.id ? 'active' : ''}`}
                onClick={() => setActiveChannelId(channel.id)}
              >
                <div className="channel-info">
                  <div className="channel-avatar">
                    {channel.avatar_path ? (
                      <img src={`/${channel.avatar_path}`} alt={channel.name} />
                    ) : (
                      <Youtube size={20} />
                    )}
                  </div>
                  <span className="channel-name">{channel.name}</span>
                </div>
                <button 
                  className="icon-button danger delete-btn" 
                  onClick={(e) => { e.stopPropagation(); handleDeleteChannel(channel.id); }}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            {channels.length === 0 && !isCreatingChannel && (
              <div className="empty-state-mini">No channels yet</div>
            )}
          </div>
        </aside>

        <main className="youtube-content">
          {activeChannel ? (
            <>
              <header className="content-header tabs-header">
                <div className="channel-title">
                  <div className="channel-avatar large">
                    {activeChannel.avatar_path ? (
                      <img src={`/${activeChannel.avatar_path}`} alt={activeChannel.name} />
                    ) : (
                      <Youtube size={28} />
                    )}
                  </div>
                  <div className="title-and-tabs">
                    <h1>{activeChannel.name}</h1>
                    <div className="channel-tabs">
                      <button 
                        className={`tab-btn ${activeTab === 'prompts' ? 'active' : ''}`}
                        onClick={() => setActiveTab('prompts')}
                      >
                        Prompts
                      </button>
                      <button 
                        className={`tab-btn ${activeTab === 'references' ? 'active' : ''}`}
                        onClick={() => setActiveTab('references')}
                      >
                        Reference Links
                      </button>
                    </div>
                  </div>
                </div>
                {activeTab === 'prompts' && !isEditingPrompt && (
                  <button className="primary" onClick={() => {
                    setPromptForm({ name: '', content: '' });
                    setIsEditingPrompt(true);
                  }}>
                    <Plus size={16} /> New Prompt
                  </button>
                )}
                {activeTab === 'references' && !isEditingRef && (
                  <button className="primary" onClick={() => {
                    setNewRefUrl('');
                    setIsEditingRef(true);
                  }}>
                    <Plus size={16} /> New Link
                  </button>
                )}
              </header>

              {activeTab === 'prompts' && (
                isEditingPrompt ? (
                  <form className="prompt-editor" onSubmit={handleSavePrompt}>
                    <div className="editor-header">
                      <h2>{promptForm.id ? 'Edit Prompt' : 'Create New Prompt'}</h2>
                      <button type="button" className="icon-button quiet" onClick={() => setIsEditingPrompt(false)}>
                        <X size={20} />
                      </button>
                    </div>
                    
                    <div className="editor-body">
                      <div className="form-group">
                        <label>Prompt Name</label>
                        <input 
                          value={promptForm.name} 
                          onChange={e => setPromptForm({...promptForm, name: e.target.value})} 
                          placeholder="e.g. Tech Review Template" 
                          required
                        />
                      </div>
                      
                      <div className="form-group flex-fill">
                        <label>Prompt Content</label>
                        <textarea 
                          value={promptForm.content} 
                          onChange={e => setPromptForm({...promptForm, content: e.target.value})} 
                          placeholder="Write your detailed prompt here..."
                          required
                        />
                      </div>
                    </div>
                    
                    <div className="editor-footer">
                      <button type="button" className="quiet" onClick={() => setIsEditingPrompt(false)}>Cancel</button>
                      <button type="submit" className="primary"><Save size={16} /> Save Prompt</button>
                    </div>
                  </form>
                ) : (
                  <div className="prompts-grid">
                    {prompts.map(prompt => (
                      <div key={prompt.id} className="prompt-card">
                        <div className="prompt-header">
                          <h3>{prompt.name}</h3>
                          <div className="prompt-actions">
                            <button className="icon-button quiet" onClick={() => copyToClipboard(prompt.content, `prompt-${prompt.id}`)} title="Copy Prompt">
                              {copiedId === `prompt-${prompt.id}` ? <Check size={16} className="text-green" /> : <Copy size={16} />}
                            </button>
                            <button className="icon-button quiet" onClick={() => setViewingPrompt(prompt)} title="View Prompt">
                              <Eye size={16} />
                            </button>
                            <button className="icon-button quiet" onClick={() => {
                              setPromptForm({
                                id: prompt.id,
                                name: prompt.name,
                                content: prompt.content,
                              });
                              setIsEditingPrompt(true);
                            }}>
                              <Edit3 size={16} />
                            </button>
                            <button className="icon-button danger" onClick={() => handleDeletePrompt(prompt.id)}>
                              <Trash2 size={16} />
                            </button>
                          </div>
                        </div>
                        <div className="prompt-body">
                          <p>{prompt.content}</p>
                        </div>
                      </div>
                    ))}
                    {prompts.length === 0 && (
                      <div className="empty-state">
                        <div className="empty-icon"><Edit3 size={48} /></div>
                        <h3>No prompts found</h3>
                        <p>Create a prompt template for this channel.</p>
                        <button className="primary" onClick={() => {
                          setPromptForm({ name: '', content: '' });
                          setIsEditingPrompt(true);
                        }}>
                          <Plus size={16} /> Create Prompt
                        </button>
                      </div>
                    )}
                  </div>
                )
              )}

              {activeTab === 'references' && (
                isEditingRef ? (
                  <form className="prompt-editor" onSubmit={handleAddRef}>
                    <div className="editor-header">
                      <h2>Add Reference Link</h2>
                      <button type="button" className="icon-button quiet" onClick={() => setIsEditingRef(false)}>
                        <X size={20} />
                      </button>
                    </div>
                    
                    <div className="editor-body">
                      <div className="form-group">
                        <label>Link URL</label>
                        <input 
                          autoFocus
                          value={newRefUrl} 
                          onChange={e => setNewRefUrl(e.target.value)} 
                          placeholder="https://..." 
                          required
                        />
                      </div>
                    </div>
                    
                    <div className="editor-footer">
                      <button type="button" className="quiet" onClick={() => setIsEditingRef(false)}>Cancel</button>
                      <button type="submit" className="primary" disabled={isSavingRefs}>
                        <Save size={16} /> {isSavingRefs ? 'Saving...' : 'Save Link'}
                      </button>
                    </div>
                  </form>
                ) : (
                  <div className="references-table-container">
                    {channelRefs.length > 0 ? (
                      <div className="references-table">
                        <div className="ref-table-header">
                          <div className="ref-col-url">Link URL</div>
                          <div className="ref-col-actions">Actions</div>
                        </div>
                        <div className="ref-table-body">
                          {channelRefs.map((ref, index) => (
                            <div key={index} className="ref-table-row">
                              <div className="ref-col-url">
                                <a href={ref.url} target="_blank" rel="noopener noreferrer">{ref.url}</a>
                              </div>
                              <div className="ref-col-actions">
                                <button className="icon-button quiet" onClick={() => copyToClipboard(ref.url, `ref-${index}`)} title="Copy URL">
                                  {copiedId === `ref-${index}` ? <Check size={16} className="text-green" /> : <Copy size={16} />}
                                </button>
                                <button className="icon-button danger" onClick={() => handleDeleteRef(index)} title="Delete Link">
                                  <Trash2 size={16} />
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <div className="empty-state">
                        <div className="empty-icon"><LinkIcon size={48} /></div>
                        <h3>No reference links</h3>
                        <p>Add some links to gather resources.</p>
                        <button className="primary" onClick={() => {
                          setNewRefUrl('');
                          setIsEditingRef(true);
                        }}>
                          <Plus size={16} /> Add Link
                        </button>
                      </div>
                    )}
                  </div>
                )
              )}
            </>
          ) : (
            <div className="empty-state main-empty">
              <div className="empty-icon"><Youtube size={64} /></div>
              <h2>Youtube Manager</h2>
              <p>Select a channel from the sidebar or create a new one to get started.</p>
            </div>
          )}
        </main>
      </div>
      
      {viewingPrompt && (
        <div className="prompt-modal-overlay" onClick={() => setViewingPrompt(null)}>
          <div className="prompt-modal" onClick={e => e.stopPropagation()}>
            <div className="prompt-modal-header">
              <h2>{viewingPrompt.name}</h2>
              <div className="prompt-modal-actions">
                <button className="icon-button quiet" onClick={() => copyToClipboard(viewingPrompt.content, `modal-prompt`)} title="Copy Content">
                  {copiedId === 'modal-prompt' ? <Check size={20} className="text-green" /> : <Copy size={20} />}
                </button>
                <button className="icon-button quiet" onClick={() => setViewingPrompt(null)}>
                  <X size={20} />
                </button>
              </div>
            </div>
            <div className="prompt-modal-body">
              <p>{viewingPrompt.content}</p>
            </div>
            <div className="prompt-modal-footer">
              <button className="primary full" onClick={() => { copyToClipboard(viewingPrompt.content, 'modal-prompt'); setTimeout(() => setViewingPrompt(null), 300); }}>
                {copiedId === 'modal-prompt' ? <Check size={16} /> : <Copy size={16} />} Copy and Close
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
