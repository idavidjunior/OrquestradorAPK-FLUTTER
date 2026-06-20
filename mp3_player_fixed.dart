// ============================================================
// MP3 PLAYER PRO - Flutter Completo (CORRIGIDO)
// Correções aplicadas:
// - media_store (inexistente) → on_audio_query
// - RepeatMode → LoopMode (just_audio)
// - Build.VERSION.SDK_INT → Platform.isAndroid + device_info_plus
// - ProcessingState importado de just_audio
// ============================================================

import 'dart:io';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:just_audio/just_audio.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:on_audio_query/on_audio_query.dart';
import 'package:device_info_plus/device_info_plus.dart';

void main() => runApp(MP3PlayerApp());

class MP3PlayerApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'MP3 Player Pro',
      theme: ThemeData(
        brightness: Brightness.dark,
        primaryColor: Color(0xFF4CAF50),
        scaffoldBackgroundColor: Color(0xFF0D0D0D),
        colorScheme: ColorScheme.dark(
          primary: Color(0xFF4CAF50),
          secondary: Color(0xFF2196F3),
          surface: Color(0xFF1A1A1A),
          background: Color(0xFF0D0D0D),
        ),
        appBarTheme: AppBarTheme(backgroundColor: Color(0xFF1A1A1A), elevation: 0),
        sliderTheme: SliderThemeData(
          activeTrackColor: Color(0xFF4CAF50),
          inactiveTrackColor: Color(0xFF333333),
          thumbColor: Color(0xFF4CAF50),
          overlayColor: Color(0xFF4CAF50).withOpacity(0.3),
        ),
      ),
      home: PlayerScreen(),
    );
  }
}

class Song {
  final int id;
  final String title;
  final String artist;
  final String album;
  final String path;
  final int duration;
  Song(this.id, this.title, this.artist, this.album, this.path, this.duration);
}

class PlayerScreen extends StatefulWidget {
  @override
  _PlayerScreenState createState() => _PlayerScreenState();
}

class _PlayerScreenState extends State<PlayerScreen> with TickerProviderStateMixin {
  final AudioPlayer _audioPlayer = AudioPlayer();
  final OnAudioQuery _audioQuery = OnAudioQuery();
  List<Song> _allSongs = [];
  List<Song> _displaySongs = [];
  Set<int> _favorites = {};
  bool _isPlaying = false;
  int _currentIndex = -1;
  Duration _position = Duration.zero;
  Duration _duration = Duration.zero;
  LoopMode _repeatMode = LoopMode.off;
  bool _shuffleOn = false;
  bool _showFavoritesOnly = false;
  int _sortMode = 0;
  bool _showEqualizer = false;
  bool _showSettings = false;
  double _bassLevel = 0.5;
  double _virtualizerLevel = 0.5;
  double _preampLevel = 0.5;
  List<double> _eqBands = List.filled(20, 0.5);
  double _playbackSpeed = 1.0;
  bool _gaplessPlayback = true;
  bool _crossfadeEnabled = false;
  double _crossfadeDuration = 3.0;
  String _audioOutput = 'Auto';
  final List<String> _sortOptions = ['Título ▲','Título ▼','Artista ▲','Artista ▼','Álbum ▲','Álbum ▼','Duração ▲','Duração ▼'];
  final List<String> _audioOutputs = ['Auto','Fones de ouvido','Alto-falante','Bluetooth'];
  final List<String> _speedOptions = ['0.5x','0.75x','1.0x','1.25x','1.5x','2.0x'];
  final List<String> _eqFreqLabels = ['32','64','125','250','500','1k','2k','4k','8k','16k','32','64','125','250','500','1k','2k','4k','8k','16k'];

  @override
  void initState() {
    super.initState();
    _initAudio();
    _loadFavorites();
    _loadSettings();
    _requestPermissionAndLoad();
  }

  Future<void> _initAudio() async {
    _audioPlayer.positionStream.listen((pos) { if (mounted) setState(() => _position = pos); });
    _audioPlayer.durationStream.listen((dur) { if (mounted && dur != null) setState(() => _duration = dur); });
    _audioPlayer.playerStateStream.listen((state) { if (mounted) setState(() => _isPlaying = state.playing); });
    _audioPlayer.processingStateStream.listen((state) {
      if (state == ProcessingState.completed) _onSongEnd();
    });
  }

  void _onSongEnd() {
    switch (_repeatMode) {
      case LoopMode.one:
        _audioPlayer.seek(Duration.zero);
        _audioPlayer.play();
        break;
      case LoopMode.all:
        _playNext();
        break;
      case LoopMode.off:
        if (_currentIndex < _displaySongs.length - 1) _playNext();
        break;
    }
  }

  Future<void> _requestPermissionAndLoad() async {
    bool needsAudioPermission = false;
    if (Platform.isAndroid) {
      try {
        final deviceInfo = DeviceInfoPlugin();
        final androidInfo = await deviceInfo.androidInfo;
        needsAudioPermission = androidInfo.version.sdkInt >= 33;
      } catch (_) {
        needsAudioPermission = false;
      }
    }

    PermissionStatus status;
    if (needsAudioPermission) {
      status = await Permission.audio.request();
    } else {
      status = await Permission.storage.request();
    }

    if (status.isGranted) {
      _loadSongsFromDevice();
    } else {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Permissão de áudio negada'), backgroundColor: Colors.red),
        );
      }
    }
  }

  Future<void> _loadSongsFromDevice() async {
    setState(() => _allSongs = []);
    try {
      final songs = await _audioQuery.querySongs(
        sortType: SongSortType.TITLE,
        orderType: OrderType.ASC_OR_SMALLER,
        uriType: UriType.EXTERNAL,
        ignoreCase: true,
      );
      List<Song> loaded = songs
          .where((s) => s.isMusic == true && (s.data?.isNotEmpty ?? false))
          .map((s) => Song(
                s.id,
                s.title,
                s.artist ?? 'Artista desconhecido',
                s.album ?? 'Álbum desconhecido',
                s.data ?? '',
                s.duration ?? 0,
              ))
          .toList();
      setState(() { _allSongs = loaded; _sortAndDisplay(); });
    } catch (e) {
      _loadSongsFallback();
    }
  }

  Future<void> _loadSongsFallback() async {
    try {
      final dir = Directory('/storage/emulated/0/Music');
      if (!await dir.exists()) {
        setState(() => _allSongs = []);
        _sortAndDisplay();
        return;
      }
      List<Song> loaded = [];
      await for (var entity in dir.list(recursive: true)) {
        if (entity is File) {
          String path = entity.path;
          if (path.endsWith('.mp3') || path.endsWith('.wav') || path.endsWith('.flac') ||
              path.endsWith('.aac') || path.endsWith('.ogg') || path.endsWith('.m4a')) {
            String fileName = path.split('/').last.replaceAll(RegExp(r'\.(mp3|wav|flac|aac|ogg|m4a)$'), '');
            loaded.add(Song(loaded.length, fileName, 'Artista desconhecido', '', path, 0));
          }
        }
      }
      setState(() { _allSongs = loaded; _sortAndDisplay(); });
    } catch (e) {
      setState(() => _allSongs = []);
      _sortAndDisplay();
    }
  }

  Future<void> _loadFavorites() async {
    final prefs = await SharedPreferences.getInstance();
    final favs = prefs.getStringList('favorites') ?? [];
    setState(() => _favorites = favs.map((s) => int.parse(s)).toSet());
  }

  Future<void> _saveFavorites() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList('favorites', _favorites.map((e) => e.toString()).toList());
  }

  Future<void> _loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _playbackSpeed = prefs.getDouble('playbackSpeed') ?? 1.0;
      _gaplessPlayback = prefs.getBool('gaplessPlayback') ?? true;
      _crossfadeEnabled = prefs.getBool('crossfadeEnabled') ?? false;
      _crossfadeDuration = prefs.getDouble('crossfadeDuration') ?? 3.0;
      _audioOutput = prefs.getString('audioOutput') ?? 'Auto';
      _bassLevel = prefs.getDouble('bassLevel') ?? 0.5;
      _virtualizerLevel = prefs.getDouble('virtualizerLevel') ?? 0.5;
      _preampLevel = prefs.getDouble('preampLevel') ?? 0.5;
      List<String>? eq = prefs.getStringList('eqBands');
      if (eq != null && eq.length == 20) _eqBands = eq.map((s) => double.parse(s)).toList();
    });
    _audioPlayer.setSpeed(_playbackSpeed);
  }

  Future<void> _saveSettings() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setDouble('playbackSpeed', _playbackSpeed);
    await prefs.setBool('gaplessPlayback', _gaplessPlayback);
    await prefs.setBool('crossfadeEnabled', _crossfadeEnabled);
    await prefs.setDouble('crossfadeDuration', _crossfadeDuration);
    await prefs.setString('audioOutput', _audioOutput);
    await prefs.setDouble('bassLevel', _bassLevel);
    await prefs.setDouble('virtualizerLevel', _virtualizerLevel);
    await prefs.setDouble('preampLevel', _preampLevel);
    await prefs.setStringList('eqBands', _eqBands.map((e) => e.toString()).toList());
  }

  void _sortAndDisplay() {
    List<Song> sorted = List.from(_allSongs);
    switch (_sortMode) {
      case 0: sorted.sort((a,b) => a.title.compareTo(b.title)); break;
      case 1: sorted.sort((a,b) => b.title.compareTo(a.title)); break;
      case 2: sorted.sort((a,b) => a.artist.compareTo(b.artist)); break;
      case 3: sorted.sort((a,b) => b.artist.compareTo(a.artist)); break;
      case 4: sorted.sort((a,b) => a.album.compareTo(b.album)); break;
      case 5: sorted.sort((a,b) => b.album.compareTo(a.album)); break;
      case 6: sorted.sort((a,b) => a.duration.compareTo(b.duration)); break;
      case 7: sorted.sort((a,b) => b.duration.compareTo(a.duration)); break;
    }
    setState(() => _displaySongs = _showFavoritesOnly
        ? sorted.where((s) => _favorites.contains(s.id)).toList()
        : sorted);
  }

  Future<void> _playSong(int index) async {
    if (index < 0 || index >= _displaySongs.length) return;
    setState(() => _currentIndex = index);
    try {
      await _audioPlayer.setFilePath(_displaySongs[index].path);
      _audioPlayer.play();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Erro ao reproduzir'), backgroundColor: Colors.red),
        );
      }
    }
  }

  void _playNext() {
    if (_displaySongs.isNotEmpty) _playSong((_currentIndex + 1) % _displaySongs.length);
  }

  void _playPrevious() {
    if (_displaySongs.isNotEmpty) _playSong(_currentIndex > 0 ? _currentIndex - 1 : _displaySongs.length - 1);
  }

  void _toggleRepeat() => setState(() => _repeatMode = LoopMode.values[(_repeatMode.index + 1) % LoopMode.values.length]);

  void _toggleShuffle() {
    setState(() => _shuffleOn = !_shuffleOn);
    if (_shuffleOn && _displaySongs.isNotEmpty) {
      _displaySongs.shuffle();
      if (_currentIndex >= 0 && _currentIndex < _displaySongs.length) {
        final currentSong = _currentIndex < _allSongs.length ? _allSongs[_currentIndex] : null;
        if (currentSong != null) {
          final idx = _displaySongs.indexWhere((s) => s.id == currentSong.id);
          if (idx >= 0) {
            final current = _displaySongs.removeAt(idx);
            _displaySongs.insert(0, current);
            setState(() => _currentIndex = 0);
          }
        }
      }
    } else {
      _sortAndDisplay();
    }
  }

  void _toggleFavorite(Song song) {
    setState(() {
      if (_favorites.contains(song.id)) {
        _favorites.remove(song.id);
      } else {
        _favorites.add(song.id);
      }
    });
    _saveFavorites();
    _sortAndDisplay();
  }

  String _fmt(Duration d) => '${d.inMinutes}:${(d.inSeconds % 60).toString().padLeft(2, '0')}';

  @override
  void dispose() { _audioPlayer.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _buildTopBar(),
            Expanded(
              child: _displaySongs.isEmpty
                  ? Center(child: Text('Nenhuma música encontrada\nVerifique as permissões',
                      textAlign: TextAlign.center, style: TextStyle(color: Colors.grey[400])))
                  : ListView.builder(
                      itemCount: _displaySongs.length,
                      itemBuilder: (ctx, i) => _buildSongItem(i)),
            ),
            _buildNowPlaying(),
            if (_showEqualizer) _buildEqualizerPanel(),
            if (_showSettings) _buildSettingsPanel(),
          ],
        ),
      ),
    );
  }

  Widget _buildTopBar() {
    return Container(
      padding: EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      color: Color(0xFF1A1A1A),
      child: Row(
        children: [
          Expanded(flex:3, child: Container(
            height:36, padding:EdgeInsets.symmetric(horizontal:8),
            decoration:BoxDecoration(color:Color(0xFF252525), borderRadius:BorderRadius.circular(6)),
            child: DropdownButtonHideUnderline(child: DropdownButton<int>(
              value:_sortMode, isExpanded:true, dropdownColor:Color(0xFF252525),
              style:TextStyle(color:Colors.white, fontSize:12),
              items:_sortOptions.asMap().entries.map((e)=>DropdownMenuItem<int>(value:e.key, child:Text(e.value, style:TextStyle(fontSize:11)))).toList(),
              onChanged:(v){ setState(()=>_sortMode=v!); _sortAndDisplay(); },
            )),
          )),
          SizedBox(width:8),
          Expanded(flex:1, child: SizedBox(height:36, child: ElevatedButton(
            style:ElevatedButton.styleFrom(
              backgroundColor:_showFavoritesOnly?Color(0xFFFFD700):Color(0xFF607D8B),
              foregroundColor:_showFavoritesOnly?Colors.black:Colors.white,
              padding:EdgeInsets.zero, shape:RoundedRectangleBorder(borderRadius:BorderRadius.circular(6))),
            onPressed:(){ setState(()=>_showFavoritesOnly=!_showFavoritesOnly); _sortAndDisplay(); },
            child:Text(_showFavoritesOnly?'Todas':'★', style:TextStyle(fontSize:14)),
          ))),
          SizedBox(width:4),
          IconButton(icon:Icon(Icons.settings, color:Colors.grey[400], size:22), onPressed:()=>setState((){_showSettings=!_showSettings; _showEqualizer=false;}), padding:EdgeInsets.zero, constraints:BoxConstraints(minWidth:36, minHeight:36)),
          IconButton(icon:Icon(Icons.equalizer, color:_showEqualizer?Color(0xFFFF5722):Colors.grey[400], size:22), onPressed:()=>setState((){_showEqualizer=!_showEqualizer; _showSettings=false;}), padding:EdgeInsets.zero, constraints:BoxConstraints(minWidth:36, minHeight:36)),
        ],
      ),
    );
  }

  Widget _buildSongItem(int index) {
    final song = _displaySongs[index];
    final isCurrent = index == _currentIndex;
    final isFav = _favorites.contains(song.id);
    return InkWell(
      onTap: () => _playSong(index),
      onLongPress: () => _toggleFavorite(song),
      child: Container(
        padding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          border: Border(bottom: BorderSide(color: Color(0xFF1E1E1E), width: 0.5)),
          color: isCurrent ? Color(0xFF1A1A1A) : Colors.transparent,
        ),
        child: Row(
          children: [
            if (isCurrent) Container(width: 3, height: 30, color: Color(0xFF4CAF50), margin: EdgeInsets.only(right: 8)),
            Expanded(child: Column(crossAxisAlignment:CrossAxisAlignment.start, children: [
              Text('${isFav?'★ ':''}${song.title}',
                style:TextStyle(color:isCurrent?Color(0xFF4CAF50):Colors.white, fontSize:13, fontWeight:isCurrent?FontWeight.bold:FontWeight.normal),
                maxLines:1, overflow:TextOverflow.ellipsis),
              Text(song.artist, style:TextStyle(color:Colors.grey[400], fontSize:11), maxLines:1, overflow:TextOverflow.ellipsis),
            ])),
            if (isCurrent && _isPlaying) Icon(Icons.music_note, color: Color(0xFF4CAF50), size: 16),
          ],
        ),
      ),
    );
  }

  Widget _buildNowPlaying() {
    final song = _currentIndex >= 0 && _currentIndex < _displaySongs.length ? _displaySongs[_currentIndex] : null;
    return Container(
      padding: EdgeInsets.only(top: 8, bottom: 4, left: 12, right: 12),
      decoration: BoxDecoration(color: Color(0xFF141414), boxShadow: [BoxShadow(color: Colors.black26, blurRadius: 8, offset: Offset(0, -2))]),
      child: Column(
        children: [
          Text(song?.title ?? 'Nenhuma música', style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.bold), maxLines: 1, overflow: TextOverflow.ellipsis),
          Row(mainAxisAlignment:MainAxisAlignment.center, children: [
            Flexible(child: Text(song?.artist ?? '', style: TextStyle(color: Colors.grey[400], fontSize: 11), maxLines: 1, overflow: TextOverflow.ellipsis)),
            if (song != null && song.album.isNotEmpty) ...[
              Text(' · ', style: TextStyle(color: Colors.grey[600], fontSize: 11)),
              Flexible(child: Text(song.album, style: TextStyle(color: Colors.grey[500], fontSize: 11), maxLines: 1, overflow: TextOverflow.ellipsis)),
            ],
          ]),
          SizedBox(height: 4),
          Row(children: [
            SizedBox(width: 36, child: Text(_fmt(_position), style: TextStyle(color: Colors.grey[400], fontSize: 9))),
            Expanded(child: Slider(
              value: _duration.inMilliseconds > 0 ? _position.inMilliseconds.toDouble() / _duration.inMilliseconds.toDouble() : 0,
              onChanged: (v) => _audioPlayer.seek(Duration(milliseconds: (v * _duration.inMilliseconds).round())),
            )),
            SizedBox(width: 36, child: Text(_fmt(_duration), style: TextStyle(color: Colors.grey[400], fontSize: 9))),
          ]),
          Row(mainAxisAlignment:MainAxisAlignment.center, children: [
            Column(children: [
              IconButton(
                icon:Icon(Icons.repeat,
                  color:_repeatMode==LoopMode.off?Colors.grey[600]:(_repeatMode==LoopMode.one?Color(0xFFFF9800):Color(0xFF4CAF50)),
                  size:22),
                onPressed:_toggleRepeat, padding:EdgeInsets.zero, constraints:BoxConstraints(minWidth:36, minHeight:36)),
              Text(_repeatMode==LoopMode.off?'':(_repeatMode==LoopMode.one?'1':'ALL'), style:TextStyle(color:Colors.grey[500], fontSize:7)),
            ]),
            SizedBox(width:4),
            IconButton(icon:Icon(Icons.skip_previous, color:Colors.white, size:28), onPressed:_playPrevious),
            Container(width:48, height:48,
              decoration:BoxDecoration(shape:BoxShape.circle, color:Color(0xFF4CAF50)),
              child:IconButton(
                icon:Icon(_isPlaying?Icons.pause:Icons.play_arrow, color:Colors.white, size:30),
                onPressed:()=>_isPlaying?_audioPlayer.pause():_audioPlayer.play())),
            IconButton(icon:Icon(Icons.skip_next, color:Colors.white, size:28), onPressed:_playNext),
            SizedBox(width:4),
            Column(children: [
              IconButton(icon:Icon(Icons.shuffle, color:_shuffleOn?Color(0xFF2196F3):Colors.grey[600], size:22), onPressed:_toggleShuffle, padding:EdgeInsets.zero, constraints:BoxConstraints(minWidth:36, minHeight:36)),
              Text(_shuffleOn?'ON':'', style:TextStyle(color:Color(0xFF2196F3), fontSize:7)),
            ]),
          ]),
          Row(mainAxisAlignment:MainAxisAlignment.center, children: [
            SizedBox(width:80, child:TextButton(
              onPressed:()=>setState((){_showEqualizer=!_showEqualizer; _showSettings=false;}),
              child:Text(_showEqualizer?'Fechar EQ':'Equalizador', style:TextStyle(fontSize:10, color:Colors.white)),
              style:TextButton.styleFrom(backgroundColor:_showEqualizer?Color(0xFFFF5722):Color(0xFF607D8B), padding:EdgeInsets.symmetric(horizontal:8, vertical:2), shape:RoundedRectangleBorder(borderRadius:BorderRadius.circular(4))))),
            SizedBox(width:8),
            SizedBox(width:80, child:TextButton(
              onPressed:()=>setState((){_showSettings=!_showSettings; _showEqualizer=false;}),
              child:Text(_showSettings?'Fechar':'Config.', style:TextStyle(fontSize:10, color:Colors.white)),
              style:TextButton.styleFrom(backgroundColor:_showSettings?Color(0xFFFF5722):Color(0xFF607D8B), padding:EdgeInsets.symmetric(horizontal:8, vertical:2), shape:RoundedRectangleBorder(borderRadius:BorderRadius.circular(4))))),
          ]),
        ],
      ),
    );
  }

  Widget _buildEqualizerPanel() {
    return Container(
      padding: EdgeInsets.all(10),
      color: Color(0xFF1A1A1A),
      constraints: BoxConstraints(maxHeight: 280),
      child: SingleChildScrollView(
        child: Column(crossAxisAlignment:CrossAxisAlignment.start, children: [
          Row(mainAxisAlignment:MainAxisAlignment.spaceBetween, children: [
            Text('Equalizador 20 Bandas', style:TextStyle(color:Colors.white, fontSize:13, fontWeight:FontWeight.bold)),
            Row(children: [
              TextButton(onPressed:(){ setState((){ for(int i=0;i<20;i++) _eqBands[i]=0.5; _bassLevel=0.5; _virtualizerLevel=0.5; _preampLevel=0.5; }); _saveSettings(); }, child:Text('Reset', style:TextStyle(fontSize:10, color:Color(0xFFFF5722)))),
              TextButton(onPressed:(){ setState((){ for(int i=0;i<20;i++) _eqBands[i]=0.7; }); _saveSettings(); }, child:Text('Rock', style:TextStyle(fontSize:10, color:Color(0xFF2196F3)))),
              TextButton(onPressed:(){ setState((){ for(int i=0;i<20;i++) _eqBands[i]=(i<8?0.8:0.3); }); _saveSettings(); }, child:Text('Pop', style:TextStyle(fontSize:10, color:Color(0xFF4CAF50)))),
              TextButton(onPressed:(){ setState((){ for(int i=0;i<20;i++) _eqBands[i]=0.5; _bassLevel=0.9; }); _saveSettings(); }, child:Text('Bass', style:TextStyle(fontSize:10, color:Color(0xFFFF9800)))),
            ]),
          ]),
          SizedBox(height:8),
          Text('Pré-amplificador', style:TextStyle(color:Colors.grey[400], fontSize:10)),
          Slider(value:_preampLevel, min:0, max:1, activeColor:Color(0xFFE91E63), inactiveColor:Color(0xFF333333), thumbColor:Color(0xFFE91E63), onChanged:(v)=>setState(()=>_preampLevel=v), onChangeEnd:(v)=>_saveSettings()),
          SizedBox(height:4),
          SizedBox(height:120, child: Row(children: List.generate(20, (i) => Expanded(child: Column(children: [
            Expanded(child: RotatedBox(quarterTurns:3, child: Slider(value:_eqBands[i], min:0, max:1, activeColor:Color(0xFF4CAF50), inactiveColor:Color(0xFF333333), thumbColor:Color(0xFF4CAF50), onChanged:(v)=>setState(()=>_eqBands[i]=v), onChangeEnd:(v)=>_saveSettings()))),
            Text(_eqFreqLabels[i], style:TextStyle(color:Colors.grey[500], fontSize:7)),
          ]))))),
          SizedBox(height:8),
          Text('Bass Boost', style:TextStyle(color:Colors.grey[400], fontSize:10)),
          Slider(value:_bassLevel, min:0, max:1, activeColor:Color(0xFFFF5722), inactiveColor:Color(0xFF333333), thumbColor:Color(0xFFFF5722), onChanged:(v)=>setState(()=>_bassLevel=v), onChangeEnd:(v)=>_saveSettings()),
          Text('Virtualizer', style:TextStyle(color:Colors.grey[400], fontSize:10)),
          Slider(value:_virtualizerLevel, min:0, max:1, activeColor:Color(0xFF2196F3), inactiveColor:Color(0xFF333333), thumbColor:Color(0xFF2196F3), onChanged:(v)=>setState(()=>_virtualizerLevel=v), onChangeEnd:(v)=>_saveSettings()),
        ]),
      ),
    );
  }

  Widget _buildSettingsPanel() {
    return Container(
      padding: EdgeInsets.all(12),
      color: Color(0xFF1A1A1A),
      constraints: BoxConstraints(maxHeight: 300),
      child: SingleChildScrollView(
        child: Column(crossAxisAlignment:CrossAxisAlignment.start, children: [
          Text('Configurações', style:TextStyle(color:Colors.white, fontSize:14, fontWeight:FontWeight.bold)),
          SizedBox(height:8),
          Text('Velocidade de reprodução', style:TextStyle(color:Colors.grey[400], fontSize:11)),
          Row(children: _speedOptions.map((s) => Expanded(child: Padding(
            padding:EdgeInsets.symmetric(horizontal:2),
            child: ElevatedButton(
              style:ElevatedButton.styleFrom(
                backgroundColor:_playbackSpeed==double.parse(s.replaceAll('x',''))?Color(0xFF4CAF50):Color(0xFF333333),
                padding:EdgeInsets.symmetric(vertical:4),
                shape:RoundedRectangleBorder(borderRadius:BorderRadius.circular(4))),
              onPressed:(){ setState(()=>_playbackSpeed=double.parse(s.replaceAll('x',''))); _audioPlayer.setSpeed(_playbackSpeed); _saveSettings(); },
              child:Text(s, style:TextStyle(fontSize:10, color:Colors.white)),
            ),
          ))).toList()),
          SizedBox(height:8),
          Row(children: [
            Text('Saída de áudio', style:TextStyle(color:Colors.grey[400], fontSize:11)),
            Spacer(),
            DropdownButton<String>(
              value:_audioOutput, dropdownColor:Color(0xFF252525),
              style:TextStyle(color:Colors.white, fontSize:11),
              items:_audioOutputs.map((o)=>DropdownMenuItem(value:o, child:Text(o))).toList(),
              onChanged:(v){ setState(()=>_audioOutput=v!); _saveSettings(); },
            ),
          ]),
          SizedBox(height:4),
          SwitchListTile(title:Text('Gapless Playback', style:TextStyle(color:Colors.grey[400], fontSize:11)), value:_gaplessPlayback, activeColor:Color(0xFF4CAF50), dense:true, contentPadding:EdgeInsets.zero, onChanged:(v){ setState(()=>_gaplessPlayback=v); _saveSettings(); }),
          SwitchListTile(title:Text('Crossfade', style:TextStyle(color:Colors.grey[400], fontSize:11)), value:_crossfadeEnabled, activeColor:Color(0xFF4CAF50), dense:true, contentPadding:EdgeInsets.zero, onChanged:(v){ setState(()=>_crossfadeEnabled=v); _saveSettings(); }),
          if (_crossfadeEnabled) Row(children: [
            Text('Duração: ${_crossfadeDuration.toStringAsFixed(1)}s', style:TextStyle(color:Colors.grey[400], fontSize:10)),
            Expanded(child: Slider(value:_crossfadeDuration, min:1, max:10, divisions:9, activeColor:Color(0xFF4CAF50), inactiveColor:Color(0xFF333333), thumbColor:Color(0xFF4CAF50), onChanged:(v)=>setState(()=>_crossfadeDuration=v), onChangeEnd:(v)=>_saveSettings())),
          ]),
          SwitchListTile(title:Text('Salvar posição ao fechar', style:TextStyle(color:Colors.grey[400], fontSize:11)), value:true, activeColor:Color(0xFF4CAF50), dense:true, contentPadding:EdgeInsets.zero, onChanged:(v){}),
          SizedBox(height:8),
          Center(child: TextButton.icon(icon:Icon(Icons.refresh, color:Color(0xFF4CAF50), size:18), onPressed:_requestPermissionAndLoad, label:Text('Reescanear músicas', style:TextStyle(color:Color(0xFF4CAF50), fontSize:12)))),
        ]),
      ),
    );
  }
}
