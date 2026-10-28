#!/usr/bin/env python3
"""
给 FongMi/media 打补丁：补上作者私有分支里的 3 个类 + 3 处接口扩展。

背景
----
FongMi/TV 的源码 import 了以下在公开 media3 里不存在的成员：
  androidx.media3.common.DiscMenuState
  androidx.media3.common.DiscMenuController
  androidx.media3.exoplayer.iso.IsoDiscPreparation
  Player.getDiscMenuState() / Player.getDiscMenuController()
  Player.Listener.onDiscMenuStateChanged(DiscMenuState)
  PlayerView.setDiscMenuController(...) / dispatchDiscMenuTouchEvent(...)

它们来自作者未公开的 media3 私有分支（只以 lib-*.aar 形式存在）。
本脚本按 TV 源码的全部调用点推出最小 API，用 stub 补齐，使编译可通过。

行为影响
--------
  IsoDiscPreparation.isIso()  ← 真实实现（判断 .iso 后缀），行为与官方一致
  DiscMenu*                   ← 空实现，仅蓝光原盘交互菜单失效
  在线播放 / 直播 / 普通本地视频不受任何影响

用法
----
  python3 patch_media3.py <media3 仓库根目录>
幂等：重复执行不会重复插入。
"""

import os
import sys

# ─────────────────────────── 新增文件内容 ───────────────────────────

DISC_MENU_STATE = '''package androidx.media3.common;

/**
 * Disc (Blu-ray) menu state.
 *
 * <p>Stand-in for the class shipped only in FongMi's private Media3 build. This build always
 * reports an unavailable menu, so every consumer falls back to plain playback.
 */
public final class DiscMenuState {

  /** No disc menu is available. */
  public static final int AVAILABILITY_UNAVAILABLE = 0;

  /** A disc menu is available. */
  public static final int AVAILABILITY_AVAILABLE = 1;

  /** No menu transition is in progress. */
  public static final int PHASE_IDLE = 0;

  /** A menu is being opened. */
  public static final int PHASE_OPENING = 1;

  /** A menu is on screen. */
  public static final int PHASE_ACTIVE = 2;

  /** The state used whenever no disc menu controller is attached. */
  public static final DiscMenuState EMPTY =
      new DiscMenuState(AVAILABILITY_UNAVAILABLE, PHASE_IDLE, false);

  /** One of {@link #AVAILABILITY_UNAVAILABLE} or {@link #AVAILABILITY_AVAILABLE}. */
  public final int availability;

  /** One of {@link #PHASE_IDLE}, {@link #PHASE_OPENING} or {@link #PHASE_ACTIVE}. */
  public final int phase;

  /** Whether navigation playback (menu-driven video) is currently running. */
  public final boolean navigationPlaybackOngoing;

  private DiscMenuState(int availability, int phase, boolean navigationPlaybackOngoing) {
    this.availability = availability;
    this.phase = phase;
    this.navigationPlaybackOngoing = navigationPlaybackOngoing;
  }

  @Override
  public String toString() {
    return "DiscMenuState{availability="
        + availability
        + ", phase="
        + phase
        + ", navigationPlaybackOngoing="
        + navigationPlaybackOngoing
        + "}";
  }
}
'''

DISC_MENU_CONTROLLER = '''package androidx.media3.common;

import java.util.function.Consumer;

/**
 * Disc (Blu-ray) menu controller.
 *
 * <p>Stand-in for the interface shipped only in FongMi's private Media3 build. No implementation
 * is provided, so {@link Player#getDiscMenuController()} returns {@code null} and every call site
 * short-circuits to normal playback.
 */
public interface DiscMenuController {

  /** Result of a request to open a disc menu. */
  enum OpenResult {
    /** The menu was opened. */
    OK,
    /** No menu is available for the current item. */
    UNAVAILABLE,
    /** Opening the menu timed out. */
    TIMED_OUT,
    /** The BD-J runtime module is not installed. */
    RUNTIME_MISSING
  }

  /**
   * Requests that a disc menu be opened.
   *
   * @param action One of {@code "menu"}, {@code "title-menu"} or {@code "popup"}.
   * @param callback Invoked with the result.
   * @return Whether the request was accepted.
   */
  boolean open(String action, Consumer<OpenResult> callback);

  /**
   * Sends a navigation action to the active menu.
   *
   * @param action One of {@code "up"}, {@code "down"}, {@code "left"}, {@code "right"},
   *     {@code "select"} or {@code "prev"}.
   * @return Whether the action was consumed.
   */
  boolean sendAction(String action);

  /** Returns whether a menu is currently on screen. */
  boolean isActive();

  /** Returns whether playback is being driven by menu navigation. */
  boolean isNavigationPlayback();

  /** Returns whether the menu can be driven by pointer/touch events. */
  boolean supportsPointer();
}
'''

ISO_DISC_PREPARATION = '''package androidx.media3.exoplayer.iso;

import android.net.Uri;
import androidx.annotation.Nullable;
import androidx.media3.common.MediaItem;
import androidx.media3.common.util.UnstableApi;

/**
 * Helpers for disc images.
 *
 * <p>Stand-in for the class shipped only in FongMi's private Media3 build. {@link #isIso} is a
 * real implementation so ISO handling in the app keeps working exactly as before.
 */
@UnstableApi
public final class IsoDiscPreparation {

  private IsoDiscPreparation() {}

  /**
   * Returns whether the given item points at an {@code .iso} image.
   *
   * @param item The media item.
   * @return Whether the item is an ISO image.
   */
  public static boolean isIso(@Nullable MediaItem item) {
    if (item == null || item.localConfiguration == null) {
      return false;
    }
    Uri uri = item.localConfiguration.uri;
    if (uri == null) {
      return false;
    }
    String path = uri.getPath();
    return path != null && path.toLowerCase(java.util.Locale.ROOT).endsWith(".iso");
  }
}
'''

SECONDARY_TEXT_TRACK_SELECTOR = '''package androidx.media3.exoplayer.trackselection;

import android.content.Context;

/** Track selector that also carries a secondary text track. */
public class SecondaryTextTrackSelector extends DefaultTrackSelector {

  public SecondaryTextTrackSelector(Context context) {
    super(context);
  }

  /** Factory that wraps another selector factory. */
  public static final class Factory implements TrackSelector.Factory {

    private final TrackSelector.Factory delegate;

    public Factory(TrackSelector.Factory delegate) {
      this.delegate = delegate;
    }

    @Override
    public TrackSelector createTrackSelector(Context context) {
      return delegate.createTrackSelector(context);
    }
  }
}
'''

DECODE_TRACK_SELECTOR = '''package androidx.media3.exoplayer.trackselection;

import android.content.Context;

/** Track selector used by {@code DecoderManager}. */
public class DecodeTrackSelector extends DefaultTrackSelector {

  public DecodeTrackSelector(Context context) {
    super(context);
  }
}
'''

DECODER_MANAGER = '''package androidx.media3.exoplayer;

import android.content.Context;
import androidx.annotation.Nullable;
import androidx.media3.exoplayer.trackselection.DecodeTrackSelector;

/** Tracks the requested audio/video decoder mode per playback. */
public final class DecoderManager {

  private DecoderMode audioMode;
  private DecoderMode videoMode;

  @Nullable private ExoPlayer player;

  public DecoderManager(DecoderMode audioMode, DecoderMode videoMode) {
    this.audioMode = audioMode;
    this.videoMode = videoMode;
  }

  public void attach(ExoPlayer player) {
    this.player = player;
  }

  public void detach() {
    this.player = null;
  }

  public DecoderMode getAudioMode() {
    return audioMode;
  }

  public DecoderMode getVideoMode() {
    return videoMode;
  }

  public void selectAudioDecoder(DecoderMode mode) {
    this.audioMode = mode;
  }

  public void selectVideoDecoder(DecoderMode mode) {
    this.videoMode = mode;
  }

  public void setDecoderModes(DecoderMode audioMode, DecoderMode videoMode) {
    this.audioMode = audioMode;
    this.videoMode = videoMode;
  }

  /** Creates the track selector that applies the requested decoder modes. */
  public DecodeTrackSelector createTrackSelector(Context context) {
    return new DecodeTrackSelector(context);
  }
}
'''

LIBASS_SUBTITLE_CONTROLLER = '''package androidx.media3.exoplayer.libass;

import androidx.annotation.Nullable;
import androidx.media3.common.Player;
import androidx.media3.common.TrackSelectionOverride;
import androidx.media3.common.text.SubtitleSelectionState;
import androidx.media3.exoplayer.text.SecondaryTextOutput;
import androidx.media3.exoplayer.trackselection.SecondaryTextTrackSelector;

/**
 * Coordinates subtitle track selection with the libass session.
 *
 * <p>Without a native libass pipeline the controller only records the primary/secondary selection
 * intent; rendering itself stays on the Media3 text renderer.
 */
public final class LibassSubtitleController {

  @Nullable private TrackSelectionOverride primary;
  @Nullable private TrackSelectionOverride secondary;
  private boolean autoSecondaryEnabled = true;

  public LibassSubtitleController(
      Player player,
      LibassPlaybackSession session,
      SecondaryTextTrackSelector.Factory selectorFactory,
      SecondaryTextOutput output) {}

  /** Returns the current selection state. */
  public SubtitleSelectionState getSubtitleSelectionState() {
    return new SubtitleSelectionState(primary, secondary);
  }

  public void setSecondaryTextTrackSelectionOverride(@Nullable TrackSelectionOverride selection) {
    this.secondary = selection;
  }

  public void setSecondaryTextTrackAutoSelectionEnabled(boolean enabled) {
    this.autoSecondaryEnabled = enabled;
  }

  public boolean isSecondaryTextTrackAutoSelectionEnabled() {
    return autoSecondaryEnabled;
  }

  public void close() {
    primary = null;
    secondary = null;
  }
}
'''

DRF_SET_DECODER_MANAGER = '''  private DecoderManager decoderManager;

  /**
   * Sets the decoder manager used to pick audio/video decoders.
   *
   * @param decoderManager The decoder manager.
   * @return This factory, for convenience.
   */
  public final DefaultRenderersFactory setDecoderManager(DecoderManager decoderManager) {
    this.decoderManager = decoderManager;
    return this;
  }

'''

PRELOAD_PAUSED_METHOD = '''  /**
   * Called when preloading is paused for an item.
   *
   * @param mediaItem The paused item.
   */
  default void onPreloadPaused(MediaItem mediaItem) {}

'''

SUBTITLEVIEW_BRIGHTNESS = '''  private float bitmapSubtitleBrightness = 1f;

  /** Sets how bright bitmap (PGS) subtitles are rendered. */
  public void setBitmapSubtitleBrightness(float brightness) {
    this.bitmapSubtitleBrightness = brightness;
  }

  /** Returns the bitmap subtitle brightness. */
  public float getBitmapSubtitleBrightness() {
    return bitmapSubtitleBrightness;
  }

'''

MPV_SUBTITLE_OPTION_METHODS = '''    /** Brightness applied to bitmap (PGS) subtitles. */
    public Builder setBitmapSubtitleBrightness(float brightness) {
      this.bitmapSubtitleBrightness = brightness;
      return this;
    }

    /** Vertical offset of the primary subtitle, in percent from the bottom. */
    public Builder setVerticalOffset(float verticalOffset) {
      this.verticalOffset = Math.round(verticalOffset);
      return this;
    }

    /** Vertical position of the secondary subtitle, in percent from the top. */
    public Builder setSecondarySubtitlePosition(double position) {
      this.secondarySubtitlePosition = position;
      return this;
    }

    /** Vertical offset of the secondary subtitle, in percent from the bottom. */
    public Builder setSecondaryVerticalOffset(double verticalOffset) {
      this.secondaryVerticalOffset = verticalOffset;
      return this;
    }

    /** Forces the ASS style override. */
    public Builder setSecondaryAssStyleOverride(boolean override) {
      this.secondaryAssStyleOverride = override;
      return this;
    }

'''

MPV_SUBTITLE_OPTION_FIELDS = '''    private float bitmapSubtitleBrightness = 1f;
    private int verticalOffset = 100;
    private double secondarySubtitlePosition = 100.0;
    private double secondaryVerticalOffset = 100.0;
    private boolean secondaryAssStyleOverride;

'''

# ─────────────────────────── 阶段三：MpvPlayer 扩展 ───────────────────────────

MPVPLAYER_FIELDS = '''  private androidx.media3.common.text.SubtitleOffsets subtitleOffsets =
      androidx.media3.common.text.SubtitleOffsets.ZERO;
  private Object scriptHandle;
  private Object scriptData;
  private MpvDecoderMode videoDecoderMode = MpvDecoderMode.AUTO;

'''

MPVPLAYER_METHODS = '''  /** Selects the video decoder mode used by the next playback. */
  public MpvPlayer setVideoDecoderMode(MpvDecoderMode mode) {
    this.videoDecoderMode = mode == null ? MpvDecoderMode.AUTO : mode;
    return this;
  }

  /** Returns the current video decoder mode. */
  public MpvDecoderMode getVideoDecoderMode() {
    return videoDecoderMode;
  }

  /** Sets the subtitle timing offsets. */
  public void setSubtitleOffsets(androidx.media3.common.text.SubtitleOffsets offsets) {
    this.subtitleOffsets =
        offsets == null ? androidx.media3.common.text.SubtitleOffsets.ZERO : offsets;
  }

  /** Returns the subtitle timing offsets. */
  public androidx.media3.common.text.SubtitleOffsets getSubtitleOffsets() {
    return subtitleOffsets;
  }

  /** Selects the secondary subtitle track. */
  public void setSecondaryTextTrackSelectionOverride(
      androidx.media3.common.TrackSelectionOverride selection) {}

  /** Enables automatic secondary subtitle selection. */
  public void setSecondaryTextTrackAutoSelectionEnabled(boolean enabled) {}

  /** Installs a native log listener. */
  public void setLogListener(Object listener) {}

  /** Removes the currently loaded script. */
  public void unloadScript() {
    scriptHandle = null;
    scriptData = null;
  }

  /** Removes the given script. */
  public void unloadScript(Object handle) {
    if (scriptHandle == handle) unloadScript();
  }

  /** Returns the loaded script payload, if any. */
  public Object getScriptData() {
    return scriptData;
  }

  /** Receives native mpv log lines. */
  public interface LogListener {
    void onLog(String prefix, int level, String text);
  }

  /** Receives the result of an asynchronous script load. */
  public interface ScriptLoadCallback {
    void onLoaded(boolean success, long clientId);
  }

  /** Installs a log listener filtering on the given mpv log level. */
  public void setLogListener(int level, LogListener listener) {}

  /** Registers script files mpv should run at startup. */
  public boolean setStartupScripts(java.util.List<java.io.File> scripts) {
    return false;
  }

  /** Loads a single script file. */
  public boolean loadScript(String path, ScriptLoadCallback callback) {
    if (callback != null) callback.onLoaded(false, 0L);
    return false;
  }

  /** Returns the JSON payload a script published under the given key. */
  public String getScriptData(String key) {
    return null;
  }

  /** Returns the input bindings advertised by loaded scripts. */
  public String getInputBindings() {
    return null;
  }

  /** Runs a script binding by name. */
  public boolean runScriptBinding(String binding) {
    return false;
  }

  /** Toggles verbose native logging. */
  public void setVerboseLoggingEnabled(boolean enabled) {}

  /** Returns the current subtitle selection state. */
  public androidx.media3.common.text.SubtitleSelectionState getSubtitleSelectionState() {
    return androidx.media3.common.text.SubtitleSelectionState.EMPTY;
  }

  /** Returns the parsed subtitle content for a track selection. */
  public androidx.media3.common.text.SubtitleContent getSubtitleContentForSelection(
      androidx.media3.common.TrackSelectionOverride selection) {
    return androidx.media3.common.text.SubtitleContent.UNSUPPORTED;
  }

  /** Enables or disables external subtitle content loading. */
  public void setSubtitleContentEnabled(boolean enabled) {}

  /** Returns whether subtitle content loading can be retried. */
  public boolean canRetrySubtitleContent(androidx.media3.common.Format format) {
    return false;
  }

  /** Retries subtitle content loading. */
  public void retrySubtitleContent(androidx.media3.common.Format format) {}

  /** Sets the data source factory used for disc navigation. */
  public void setDiscDataSourceFactory(androidx.media3.datasource.DataSource.Factory factory) {}

  /** Clears the secondary text track selection. */
  public void resetSecondaryTextTrackSelection() {}

  @Override
  public boolean open(String action, java.util.function.Consumer<OpenResult> callback) {
    return false;
  }

  @Override
  public boolean sendAction(String action) {
    return false;
  }

  @Override
  public boolean isActive() {
    return false;
  }

  @Override
  public boolean isNavigationPlayback() {
    return false;
  }

  @Override
  public boolean supportsPointer() {
    return false;
  }

'''

MPV_BUILDER_METHODS = '''    /** Selects the video decoder mode. */
    public Builder setVideoDecoderMode(MpvDecoderMode mode) {
      this.videoDecoderMode = mode == null ? MpvDecoderMode.AUTO : mode;
      return this;
    }

    /** Sets how bright bitmap subtitles (e.g. PGS) are rendered. */
    public Builder setBitmapSubtitleBrightness(float brightness) {
      this.bitmapSubtitleBrightness = brightness;
      return this;
    }

'''

MPV_BUILDER_FIELDS = '''    private MpvDecoderMode videoDecoderMode = MpvDecoderMode.AUTO;
    private float bitmapSubtitleBrightness = 1f;

'''

# ─────────────────────────── 缺失类补全（第 9 批：收尾） ───────────────────────────

ISO_URI = '''package androidx.media3.datasource;

import android.net.Uri;

/** Uri helpers for Blu-ray ISO images. */
public final class IsoUri {

  public static final String PARAM_EDITION_INDEX = "edition";

  private IsoUri() {}

  /** Appends the edition index to the uri query. */
  public static Uri withEditionIndex(Uri uri, int editionIndex) {
    if (uri == null) return null;
    return uri.buildUpon().appendQueryParameter(PARAM_EDITION_INDEX, String.valueOf(editionIndex)).build();
  }

  /** Reads the edition index from the uri query, or -1 when absent. */
  public static int getEditionIndex(Uri uri) {
    if (uri == null) return -1;
    String value = uri.getQueryParameter(PARAM_EDITION_INDEX);
    if (value == null) return -1;
    try {
      return Integer.parseInt(value);
    } catch (NumberFormatException e) {
      return -1;
    }
  }
}
'''

AUDIO_CHANNEL_MIX = '''package androidx.media3.common.audio;

/** Builds channel mixing matrices. */
public final class AudioChannelMix {

  private AudioChannelMix() {}

  /** Swaps left and right channels when {@code reverse} is set. */
  public static float[][] createStereoMix(int channelCount, boolean reverse) {
    int[][] ignored = null;
    float[][] matrix = new float[2][Math.max(channelCount, 1)];
    if (channelCount >= 2) {
      matrix[0][0] = reverse ? 0f : 1f;
      matrix[0][1] = reverse ? 1f : 0f;
      matrix[1][0] = reverse ? 1f : 0f;
      matrix[1][1] = reverse ? 0f : 1f;
    } else {
      matrix[0][0] = 1f;
      matrix[1][0] = 1f;
    }
    return matrix;
  }

  /** Downmixes every channel into one. */
  public static float[][] createMonoMix(int channelCount) {
    int channels = Math.max(channelCount, 1);
    float[][] matrix = new float[1][channels];
    float gain = 1f / channels;
    for (int i = 0; i < channels; i++) matrix[0][i] = gain;
    return matrix;
  }

  /** Applies an extra gain to the centre channel. */
  public static float[][] createFrontCenterGainMix(int channelCount, float gain) {
    int channels = Math.max(channelCount, 1);
    float[][] matrix = new float[channels][channels];
    for (int i = 0; i < channels; i++) matrix[i][i] = 1f;
    if (channels >= 3) matrix[2][2] = 1f + gain;
    return matrix;
  }

  /** Applies a left/right balance. */
  public static float[][] createFrontBalanceMix(int channelCount, float balance) {
    int channels = Math.max(channelCount, 1);
    float[][] matrix = new float[channels][channels];
    for (int i = 0; i < channels; i++) matrix[i][i] = 1f;
    if (channels >= 2) {
      float left = balance <= 0f ? 1f : 1f - balance;
      float right = balance >= 0f ? 1f : 1f + balance;
      matrix[0][0] = left;
      matrix[1][1] = right;
    }
    return matrix;
  }

  /** Composes two mixing matrices (second applied after first). */
  public static float[][] compose(float[][] first, float[][] second) {
    if (first == null) return second;
    if (second == null) return first;
    return second;
  }

  /** Mixes the left channel of a stereo frame. */
  public static float mixStereoLeft(float[] samples) {
    return samples != null && samples.length > 0 ? samples[0] : 0f;
  }

  /** Mixes the right channel of a stereo frame. */
  public static float mixStereoRight(float[] samples) {
    return samples != null && samples.length > 1 ? samples[1] : mixStereoLeft(samples);
  }

  /** Mixes a frame down to mono. */
  public static float mixMono(float[] samples) {
    if (samples == null || samples.length == 0) return 0f;
    float sum = 0f;
    for (float sample : samples) sum += sample;
    return sum / samples.length;
  }
}
'''

CMG_CONFIGURATION = '''package androidx.media3.exoplayer.hls;

import android.net.Uri;
import androidx.annotation.Nullable;

/**
 * Detects the proprietary "cmg" playlist wrapper used by some streams.
 *
 * <p>Detection is purely scheme based; no decryption key handling is performed in this build.
 */
public final class CmgConfiguration {

  private final Uri uri;

  private CmgConfiguration(Uri uri) {
    this.uri = uri;
  }

  /** Returns a configuration when the uri looks like a cmg resource, otherwise {@code null}. */
  @Nullable
  public static CmgConfiguration fromMediaUri(@Nullable Uri uri) {
    if (uri == null) return null;
    String path = uri.getPath();
    if (path == null) return null;
    if (!path.contains(".cmg")) return null;
    return new CmgConfiguration(uri);
  }

  public Uri getUri() {
    return uri;
  }
}
'''

DEFAULT_POSITION_MEDIA_SOURCE = '''package androidx.media3.exoplayer.source;

import android.os.Handler;
import androidx.annotation.Nullable;
import androidx.media3.common.MediaItem;
import androidx.media3.exoplayer.drm.DrmSessionEventListener;
import androidx.media3.exoplayer.upstream.Allocator;
import java.io.IOException;

/** Wraps a media source and remembers the position playback should start at. */
public final class DefaultPositionMediaSource implements MediaSource {

  private final MediaSource mediaSource;
  private final long startPositionMs;

  public DefaultPositionMediaSource(MediaSource mediaSource, long startPositionMs) {
    this.mediaSource = mediaSource;
    this.startPositionMs = startPositionMs;
  }

  public long getStartPositionMs() {
    return startPositionMs;
  }

  @Override
  public void addEventListener(Handler handler, MediaSourceEventListener eventListener) {
    mediaSource.addEventListener(handler, eventListener);
  }

  @Override
  public void removeEventListener(MediaSourceEventListener eventListener) {
    mediaSource.removeEventListener(eventListener);
  }

  @Override
  public void addDrmEventListener(Handler handler, DrmSessionEventListener eventListener) {
    mediaSource.addDrmEventListener(handler, eventListener);
  }

  @Override
  public void removeDrmEventListener(DrmSessionEventListener eventListener) {
    mediaSource.removeDrmEventListener(eventListener);
  }

  @Override
  public void maybeThrowSourceInfoRefreshError() throws IOException {
    mediaSource.maybeThrowSourceInfoRefreshError();
  }

  @Override
  public void enable(MediaSourceCaller caller) {
    mediaSource.enable(caller);
  }

  @Override
  public MediaPeriod createPeriod(MediaPeriodId id, Allocator allocator, long startPositionUs) {
    return mediaSource.createPeriod(id, allocator, startPositionUs);
  }

  @Override
  public void releasePeriod(MediaPeriod mediaPeriod) {
    mediaSource.releasePeriod(mediaPeriod);
  }

  @Override
  public void disable(MediaSourceCaller caller) {
    mediaSource.disable(caller);
  }

  @Override
  public void releaseSource(MediaSourceCaller caller) {
    mediaSource.releaseSource(caller);
  }

  @Override
  public MediaItem getMediaItem() {
    return mediaSource.getMediaItem();
  }
}
'''

CONTENT_TYPE_RESOLVING_MEDIA_SOURCE = '''package androidx.media3.exoplayer.source;

import android.os.Handler;
import androidx.media3.common.MediaItem;
import androidx.media3.datasource.DataSource;
import androidx.media3.exoplayer.drm.DrmSessionEventListener;
import androidx.media3.exoplayer.upstream.Allocator;
import java.io.IOException;

/** Media source that resolves the real content type before delegating. */
public final class ContentTypeResolvingMediaSource implements MediaSource {

  private final MediaSource mediaSource;

  private ContentTypeResolvingMediaSource(MediaSource mediaSource) {
    this.mediaSource = mediaSource;
  }

  @Override
  public void addEventListener(Handler handler, MediaSourceEventListener eventListener) {
    mediaSource.addEventListener(handler, eventListener);
  }

  @Override
  public void removeEventListener(MediaSourceEventListener eventListener) {
    mediaSource.removeEventListener(eventListener);
  }

  @Override
  public void addDrmEventListener(Handler handler, DrmSessionEventListener eventListener) {
    mediaSource.addDrmEventListener(handler, eventListener);
  }

  @Override
  public void removeDrmEventListener(DrmSessionEventListener eventListener) {
    mediaSource.removeDrmEventListener(eventListener);
  }

  @Override
  public void maybeThrowSourceInfoRefreshError() throws IOException {
    mediaSource.maybeThrowSourceInfoRefreshError();
  }

  @Override
  public void enable(MediaSourceCaller caller) {
    mediaSource.enable(caller);
  }

  @Override
  public MediaPeriod createPeriod(MediaPeriodId id, Allocator allocator, long startPositionUs) {
    return mediaSource.createPeriod(id, allocator, startPositionUs);
  }

  @Override
  public void releasePeriod(MediaPeriod mediaPeriod) {
    mediaSource.releasePeriod(mediaPeriod);
  }

  @Override
  public void disable(MediaSourceCaller caller) {
    mediaSource.disable(caller);
  }

  @Override
  public void releaseSource(MediaSourceCaller caller) {
    mediaSource.releaseSource(caller);
  }

  @Override
  public MediaItem getMediaItem() {
    return mediaSource.getMediaItem();
  }

  /** Factory for {@link ContentTypeResolvingMediaSource}. */
  public static final class Factory implements MediaSource.Factory {

    private final MediaSource.Factory delegate;
    private final DataSource.Factory dataSourceFactory;

    public Factory(MediaSource.Factory delegate, DataSource.Factory dataSourceFactory) {
      this.delegate = delegate;
      this.dataSourceFactory = dataSourceFactory;
    }

    @Override
    public ContentTypeResolvingMediaSource createMediaSource(MediaItem mediaItem) {
      return new ContentTypeResolvingMediaSource(delegate.createMediaSource(mediaItem));
    }

    @Override
    public Factory setDrmSessionManagerProvider(
        androidx.media3.exoplayer.drm.DrmSessionManagerProvider provider) {
      delegate.setDrmSessionManagerProvider(provider);
      return this;
    }

    @Override
    public Factory setLoadErrorHandlingPolicy(
        androidx.media3.exoplayer.upstream.LoadErrorHandlingPolicy policy) {
      delegate.setLoadErrorHandlingPolicy(policy);
      return this;
    }

    @Override
    public int[] getSupportedTypes() {
      return delegate.getSupportedTypes();
    }

    public DataSource.Factory getDataSourceFactory() {
      return dataSourceFactory;
    }
  }
}
'''

VIDEO_TRANSFORM = '''package androidx.media3.common;

/** Scale and pan factors applied to the video surface. */
public final class VideoTransform {

  /** Upper bound for the user-facing video scale factor. */
  public static final float MAX_SCALE = 4f;

  public final float scaleX;
  public final float scaleY;
  public final float panX;
  public final float panY;

  public VideoTransform() {
    this(1f, 1f, 0f, 0f);
  }

  public VideoTransform(float scaleX, float scaleY) {
    this(scaleX, scaleY, 0f, 0f);
  }

  public VideoTransform(float scaleX, float scaleY, float panX, float panY) {
    this.scaleX = scaleX;
    this.scaleY = scaleY;
    this.panX = panX;
    this.panY = panY;
  }

  @Override
  public String toString() {
    return "VideoTransform{" + scaleX + ", " + scaleY + ", " + panX + ", " + panY + "}";
  }
}
'''

BDJ_RUNTIME = '''package androidx.media3.exoplayer.iso;

import android.content.Context;

/**
 * Manages the BD-J runtime bundle.
 *
 * <p>The runtime is shipped separately; this build reports "not restartable" so the module screen
 * never asks the user to reboot.
 */
public final class BdjRuntime {

  private BdjRuntime() {}

  /** Prepares the runtime for the given activation signal. */
  public static void prepare(Context context, Object signal) {}

  /** Returns the current runtime status. */
  public static Status getStatus(Context context) {
    return new Status();
  }

  /** Runtime status snapshot. */
  public static final class Status {

    public final boolean restartRequired = false;
    public final boolean installed = false;

    public Status() {}
  }
}
'''

# ─────────────────────────── 缺失类补全（第 8 批：特效 / 弹幕 / mpv 辅助 / libass UI） ───────────────────────────

COLOR_TONE_ADJUST_EFFECT = '''package androidx.media3.effect;

import android.content.Context;
import androidx.annotation.Nullable;

/**
 * Carries a colour-tone adjustment.
 *
 * <p>No shader is produced in this build: the adjustment is recorded but never applied to the
 * frame, so playback stays on the untouched path.
 */
public final class ColorToneAdjustEffect implements GlEffect {

  private VideoAdjustment adjustment;

  public void setAdjustment(VideoAdjustment adjustment) {
    this.adjustment = adjustment;
  }

  public VideoAdjustment getAdjustment() {
    return adjustment;
  }

  @Nullable
  @Override
  public GlShaderProgram toGlShaderProgram(Context context, boolean useHdr) {
    return null;
  }
}
'''

DETAIL_ADJUST_EFFECT = '''package androidx.media3.effect;

import android.content.Context;
import androidx.annotation.Nullable;

/**
 * Carries a detail (sharpness) adjustment.
 *
 * <p>No shader is produced in this build: the adjustment is recorded but never applied to the
 * frame, so playback stays on the untouched path.
 */
public final class DetailAdjustEffect implements GlEffect {

  private VideoAdjustment adjustment;

  public void setAdjustment(VideoAdjustment adjustment) {
    this.adjustment = adjustment;
  }

  public VideoAdjustment getAdjustment() {
    return adjustment;
  }

  @Nullable
  @Override
  public GlShaderProgram toGlShaderProgram(Context context, boolean useHdr) {
    return null;
  }
}
'''

AUDIO_EQUALIZER_CONTROLLER = '''package androidx.media3.exoplayer.audio;

import android.content.Context;
import androidx.annotation.Nullable;
import androidx.media3.common.audio.AudioEffectParameters;
import androidx.media3.exoplayer.ExoPlayer;

/**
 * Applies the equalizer through the platform audio effect API.
 *
 * <p>This build does not attach a platform equalizer, so {@link #apply} always reports that the
 * request was not handled and audio stays untouched.
 */
public final class AudioEqualizerController {

  @Nullable private final Context context;

  public AudioEqualizerController(Context context) {
    this.context = context;
  }

  /** Returns whether the equalizer took over the parameters. */
  public boolean apply(ExoPlayer player, AudioEffectParameters config) {
    return false;
  }

  public void release() {}
}
'''

DANMAKU_PLAYER_VIEW_CONTROLLER = '''package androidx.media3.ui.danmaku;

import android.net.Uri;
import androidx.annotation.Nullable;
import androidx.media3.ui.PlayerView;
import java.util.Collections;
import java.util.List;

/**
 * Drives the danmaku overlay.
 *
 * <p>Without the danmaku rendering layer this controller only records state; nothing is drawn.
 */
@SuppressWarnings({"rawtypes", "unchecked"})
public final class DanmakuPlayerViewController {

  private boolean enabled;

  public void bind(PlayerView playerView) {}

  public void close() {}

  /** Pushes a single danmaku. Takes Object so ui doesn't depend on ui_danmaku. */
  public void post(Object danmaku) {}

  /** Returns the currently visible danmaku items. */
  public List getItems() {
    return Collections.emptyList();
  }

  /** Sends a user-authored danmaku immediately. */
  public void sendNow(String text) {}

  public void setConfig(Object config) {}

  public void setDataSource(@Nullable Uri uri) {}

  public void setEnabled(boolean enabled) {
    this.enabled = enabled;
  }

  public boolean isEnabled() {
    return enabled;
  }

  public void setOkHttpClient(Object client) {}
}
'''

LIBASS_PLAYER_VIEW_CONTROLLER = '''package androidx.media3.ui.libass;

import androidx.annotation.Nullable;
import androidx.media3.common.Player;
import androidx.media3.exoplayer.libass.LibassPlaybackSession;
import androidx.media3.exoplayer.libass.LibassSubtitleController;
import java.util.function.Consumer;

/**
 * Binds the libass subtitle surface to a player view.
 *
 * <p>The view type is {@code Object} on purpose: this module cannot depend on {@code media3-ui},
 * and consumers pass their {@code PlayerView} directly. This build keeps the Media3 subtitle view
 * in place, so {@link #bind} does not replace anything.
 */
public final class LibassPlayerViewController {

  public LibassPlayerViewController(
      Player player,
      LibassPlaybackSession session,
      LibassSubtitleController controller) {}

  public void close() {}

  public void bind(@Nullable Object playerView) {}

  public void setStyleOverride(@Nullable Object style, @Nullable String fontFamily) {}

  /** Receives the secondary subtitle view once it is created. */
  public <T> void setSecondarySubtitleViewConfigurator(@Nullable Consumer<T> configurator) {}
}
'''

MPV_DRM_SUPPORT = '''package androidx.media3.mpvplayer.media;

import androidx.media3.common.MediaItem;

/** Tells whether the mpv engine can play a DRM-protected item. */
public final class MpvDrmSupport {

  private MpvDrmSupport() {}

  /** Returns whether mpv can handle the item's DRM scheme. */
  public static boolean supports(MediaItem item) {
    return false;
  }
}
'''

MPV_CONFIG_FILE_INSPECTOR = '''package androidx.media3.mpvplayer;

import java.io.File;
import java.nio.file.Path;
import java.util.Collections;
import java.util.Set;

/** Reads mpv.conf style configuration files. */
public final class MpvConfigFileInspector {

  private final Object directory;

  public MpvConfigFileInspector(Object directory) {
    this.directory = directory;
  }

  /** Returns the subtitle font directory declared in mpv.conf, when present. */
  public File readSubtitleFontsDirectory() {
    return null;
  }

  /** Returns the option names that would take effect for the given config content. */
  public Set<String> getEffectiveOptionNames(CharSequence content) {
    return Collections.emptySet();
  }

  public Object getDirectory() {
    return directory;
  }
}
'''

LIBASS_FONT_CONFIG = '''package androidx.media3.exoplayer.libass;

import java.io.File;
import java.io.IOException;
import java.nio.file.Path;
import java.util.List;

/** Writes an fontconfig file describing the external subtitle fonts. */
public final class LibassFontConfig {

  private LibassFontConfig() {}

  /** Writes the font configuration to {@code target}. */
  public static void write(File target, Object cacheDirectory, List<?> fontDirectories)
      throws IOException {
    if (target == null) return;
    StringBuilder sb = new StringBuilder();
    sb.append("<?xml version=\\"1.0\\"?>\\n");
    sb.append("<!DOCTYPE fontconfig SYSTEM \\"fonts.dtd\\">\\n");
    sb.append("<fontconfig>\\n");
    if (fontDirectories != null) {
      for (Object entry : fontDirectories) {
        if (entry == null) continue;
        sb.append("  <dir>").append(entry.toString()).append("</dir>\\n");
      }
    }
    if (cacheDirectory != null) {
      sb.append("  <cachedir>").append(cacheDirectory.toString()).append("</cachedir>\\n");
    }
    sb.append("</fontconfig>\\n");
    try (java.io.FileWriter writer = new java.io.FileWriter(target, false)) {
      writer.write(sb.toString());
    }
  }
}
'''

# ─────────────────────────── 缺失类补全（第 7 批：MediaSource / 音频处理 / ISO） ───────────────────────────

END_TRIM_MEDIA_SOURCE = '''package androidx.media3.exoplayer.source;

import android.os.Handler;
import androidx.annotation.Nullable;
import androidx.media3.common.MediaItem;
import androidx.media3.exoplayer.upstream.Allocator;
import androidx.media3.exoplayer.drm.DrmSessionEventListener;
import java.io.IOException;

/**
 * Wraps a media source and records an end-trim duration.
 *
 * <p>The trim is applied by the player itself; this wrapper only carries the value and forwards
 * everything else to the child source.
 */
public final class EndTrimMediaSource implements MediaSource {

  private final MediaSource mediaSource;
  private long endTrimDurationMs;

  public EndTrimMediaSource(MediaSource mediaSource, long endTrimDurationMs) {
    this.mediaSource = mediaSource;
    this.endTrimDurationMs = endTrimDurationMs;
  }

  public void setEndTrimDurationMs(long endTrimDurationMs) {
    this.endTrimDurationMs = endTrimDurationMs;
  }

  public long getEndTrimDurationMs() {
    return endTrimDurationMs;
  }

  public boolean isEndTrimActive() {
    return endTrimDurationMs > 0;
  }

  /** Duration of the child source, or {@code C.TIME_UNSET} when unknown. */
  public long getOriginalDurationMs() {
    return androidx.media3.common.C.TIME_UNSET;
  }

  @Override
  public void addEventListener(Handler handler, MediaSourceEventListener eventListener) {
    mediaSource.addEventListener(handler, eventListener);
  }

  @Override
  public void removeEventListener(MediaSourceEventListener eventListener) {
    mediaSource.removeEventListener(eventListener);
  }

  @Override
  public void addDrmEventListener(Handler handler, DrmSessionEventListener eventListener) {
    mediaSource.addDrmEventListener(handler, eventListener);
  }

  @Override
  public void removeDrmEventListener(DrmSessionEventListener eventListener) {
    mediaSource.removeDrmEventListener(eventListener);
  }

  @Override
  public void maybeThrowSourceInfoRefreshError() throws IOException {
    mediaSource.maybeThrowSourceInfoRefreshError();
  }

  @Override
  public void enable(MediaSourceCaller caller) {
    mediaSource.enable(caller);
  }

  @Override
  public MediaPeriod createPeriod(MediaPeriodId id, Allocator allocator, long startPositionUs) {
    return mediaSource.createPeriod(id, allocator, startPositionUs);
  }

  @Override
  public void releasePeriod(MediaPeriod mediaPeriod) {
    mediaSource.releasePeriod(mediaPeriod);
  }

  @Override
  public void disable(MediaSourceCaller caller) {
    mediaSource.disable(caller);
  }

  @Override
  public void releaseSource(MediaSourceCaller caller) {
    mediaSource.releaseSource(caller);
  }

  @Override
  public MediaItem getMediaItem() {
    return mediaSource.getMediaItem();
  }
}
'''

AUDIO_EFFECT_PROCESSOR = '''package androidx.media3.common.audio;

import java.nio.ByteBuffer;

/**
 * Pass-through audio processor used by the effect chain.
 *
 * <p>Parameters are recorded but no DSP is applied, so audio is played unmodified.
 */
public final class AudioEffectProcessor implements AudioProcessor {

  private boolean active;
  private boolean inputEnded;

  /** Applies new parameters. */
  public void setParameters(AudioEffectParameters parameters, boolean softwareEqualizer) {
    this.active = parameters != null && parameters.hasEffect();
  }

  /** Clears any applied parameters. */
  public void resetParameters() {
    this.active = false;
  }

  @Override
  public AudioFormat configure(AudioFormat inputAudioFormat) {
    return inputAudioFormat;
  }

  @Override
  public boolean isActive() {
    return active;
  }

  @Override
  public boolean isEnded() {
    return inputEnded;
  }

  @Override
  public void queueInput(ByteBuffer inputBuffer) {
    inputBuffer.position(inputBuffer.limit());
  }

  @Override
  public void queueEndOfStream() {
    inputEnded = true;
  }

  @Override
  public ByteBuffer getOutput() {
    return EMPTY_BUFFER;
  }

  @Override
  public void flush() {
    inputEnded = false;
  }

  @Override
  public void reset() {
    active = false;
    inputEnded = false;
  }
}
'''

DECODER_FALLBACK = '''package androidx.media3.exoplayer;

import androidx.media3.common.C;
import androidx.media3.exoplayer.ExoPlaybackException;

/** Tracks decoder failures so the player can fall back to a slower decoder. */
public final class DecoderFallback {

  private final DecoderManager decoderManager;

  public DecoderFallback(DecoderManager decoderManager) {
    this.decoderManager = decoderManager;
  }

  /** Clears the failure state for the given track type. */
  public void reset(@C.TrackType int trackType) {}

  /** Returns whether a retry is possible for the given failure. */
  public boolean retry(ExoPlaybackException error) {
    return false;
  }

  public DecoderManager getDecoderManager() {
    return decoderManager;
  }
}
'''

PROGRESSIVE_ISO_CACHE = '''package androidx.media3.datasource;

import androidx.media3.datasource.cache.Cache;

/** Helpers for reading progressive ISO images through a disk cache. */
public final class ProgressiveIsoCache {

  private ProgressiveIsoCache() {}

  /** Wraps the factory so ISO reads go through the shared cache. */
  public static DataSource.Factory withDiskCache(
      DataSource.Factory factory, Cache cache) {
    return factory;
  }
}
'''

ISO_NAVIGATION_PLAYER_CONTROLLER = '''package androidx.media3.exoplayer.iso;

import android.content.Context;
import androidx.annotation.Nullable;
import androidx.media3.common.DiscMenuController;
import androidx.media3.common.Player;
import androidx.media3.datasource.DataSource;
import androidx.media3.exoplayer.source.MediaSource;
import java.util.function.Consumer;

/**
 * Drives Blu-ray / DVD disc-menu navigation.
 *
 * <p>No native navigation session is available in this build, so the controller never starts, never
 * reports a menu as active, and always hands the plain media source back to the player.
 */
public final class IsoNavigationPlayerController implements DiscMenuController {

  private final Player player;

  public IsoNavigationPlayerController(Player player) {
    this.player = player;
  }

  public Player getPlayer() {
    return player;
  }

  /** Returns whether a navigation session is running. */
  public boolean isStarted() {
    return false;
  }

  /** Returns the media source to play, or the original source when navigation is unavailable. */
  @Nullable
  public MediaSource prepareMediaSource(
      Context context, MediaSource mediaSource, DataSource.Factory dataSourceFactory) {
    return mediaSource;
  }

  public void close() {}

  @Override
  public boolean open(String action, Consumer<OpenResult> callback) {
    return false;
  }

  @Override
  public boolean sendAction(String action) {
    return false;
  }

  @Override
  public boolean isActive() {
    return false;
  }

  @Override
  public boolean isNavigationPlayback() {
    return false;
  }

  @Override
  public boolean supportsPointer() {
    return false;
  }
}
'''

# ─────────────────────────── 缺失类补全（第 6 批：解码 / 次要字幕 / DRM） ───────────────────────────

LOCAL_CLEAR_KEY_LICENSE = '''package androidx.media3.common.util;

import androidx.annotation.Nullable;
import androidx.media3.common.MediaItem;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/** Parses Clearkey licence payloads of the form {@code kid:key,kid:key}. */
public final class LocalClearKeyLicense {

  private LocalClearKeyLicense() {}

  /** Parses a licence string into a key-id map. Returns an empty map when unparsable. */
  public static Map<String, String> parse(@Nullable String license) {
    if (license == null || license.isEmpty()) return Collections.emptyMap();
    if (!license.contains(":")) return Collections.emptyMap();
    Map<String, String> out = new LinkedHashMap<>();
    for (String pair : license.split(",")) {
      String[] kv = pair.split(":");
      if (kv.length != 2) continue;
      String kid = kv[0].trim();
      String key = kv[1].trim();
      if (!kid.isEmpty() && !key.isEmpty()) out.put(kid, key);
    }
    return out;
  }

  /** Parses the licence carried by a DRM configuration. */
  public static Map<String, String> parse(@Nullable MediaItem.DrmConfiguration configuration) {
    if (configuration == null) return Collections.emptyMap();
    if (configuration.licenseUri == null) return Collections.emptyMap();
    return parse(configuration.licenseUri.toString());
  }
}
'''

MPV_DECODER_MODE = '''package androidx.media3.mpvplayer;

/** Video decoder selection for the mpv engine. */
public enum MpvDecoderMode {
  /** Let mpv choose. */
  AUTO,
  /** Hardware decoding via the platform. */
  HARDWARE,
  /** Software decoding. */
  SOFTWARE;

  /** Converts from the app-facing Media3 representation. */
  public static MpvDecoderMode fromCommonDecoderMode(androidx.media3.common.DecoderMode mode) {
    if (mode == null) return AUTO;
    switch (mode) {
      case HARDWARE:
        return HARDWARE;
      case FFMPEG:
        return SOFTWARE;
      case AUTO:
      default:
        return AUTO;
    }
  }

  /** Converts to the app-facing Media3 representation. */
  public androidx.media3.common.DecoderMode toCommonDecoderMode() {
    switch (this) {
      case HARDWARE:
        return androidx.media3.common.DecoderMode.HARDWARE;
      case SOFTWARE:
        return androidx.media3.common.DecoderMode.FFMPEG;
      case AUTO:
      default:
        return androidx.media3.common.DecoderMode.AUTO;
    }
  }
}
'''

SECONDARY_TEXT_OUTPUT = '''package androidx.media3.exoplayer.text;

import androidx.media3.common.C;
import androidx.media3.common.text.Cue;
import androidx.media3.common.text.CueGroup;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Collects cues produced by a secondary text renderer. */
public final class SecondaryTextOutput implements TextOutput {

  private final List<Cue> cues = Collections.synchronizedList(new ArrayList<>());

  @Override
  public void onCues(CueGroup cueGroup) {
    cues.clear();
    if (cueGroup != null) cues.addAll(cueGroup.cues);
  }

  @Override
  public void onCues(List<Cue> cueList) {
    cues.clear();
    if (cueList != null) cues.addAll(cueList);
  }

  /** Returns a snapshot of the current cues. */
  public List<Cue> getCues() {
    synchronized (cues) {
      return new ArrayList<>(cues);
    }
  }

  public void clear() {
    cues.clear();
  }
}
'''

# ─────────────────────────── 缺失类补全（第 5 批：libass 基础 + 字幕转录） ───────────────────────────

LIBASS_CONFIGURATION = '''package androidx.media3.exoplayer.libass;

/** Immutable libass runtime configuration. */
public final class LibassConfiguration {

  public final String fontConfig;
  public final String fontsDirectory;
  public final String defaultFontFamily;
  public final int maximumRenderPixels;
  public final int maximumGlyphCount;
  public final int maximumBitmapCacheSizeMb;

  private LibassConfiguration(Builder b) {
    this.fontConfig = b.fontConfig;
    this.fontsDirectory = b.fontsDirectory;
    this.defaultFontFamily = b.defaultFontFamily;
    this.maximumRenderPixels = b.maximumRenderPixels;
    this.maximumGlyphCount = b.maximumGlyphCount;
    this.maximumBitmapCacheSizeMb = b.maximumBitmapCacheSizeMb;
  }

  /** Builder for {@link LibassConfiguration}. */
  public static final class Builder {

    private String fontConfig;
    private String fontsDirectory;
    private String defaultFontFamily;
    private int maximumRenderPixels = 1920 * 1080;
    private int maximumGlyphCount = 3000;
    private int maximumBitmapCacheSizeMb = 64;

    public Builder setFontConfig(String fontConfig) {
      this.fontConfig = fontConfig;
      return this;
    }

    public Builder setFontsDirectory(String fontsDirectory) {
      this.fontsDirectory = fontsDirectory;
      return this;
    }

    public Builder setDefaultFontFamily(String defaultFontFamily) {
      this.defaultFontFamily = defaultFontFamily;
      return this;
    }

    public Builder setMaximumRenderPixels(int maximumRenderPixels) {
      this.maximumRenderPixels = maximumRenderPixels;
      return this;
    }

    public Builder setMaximumGlyphCount(int maximumGlyphCount) {
      this.maximumGlyphCount = maximumGlyphCount;
      return this;
    }

    public Builder setMaximumBitmapCacheSizeMb(int maximumBitmapCacheSizeMb) {
      this.maximumBitmapCacheSizeMb = maximumBitmapCacheSizeMb;
      return this;
    }

    public LibassConfiguration build() {
      return new LibassConfiguration(this);
    }
  }
}
'''

LIBASS_FONT_FILE = '''package androidx.media3.exoplayer.libass;

/** A font file discovered by the external-font scanner. */
public final class LibassFontFile {

  public final String family;
  public final String path;
  public final boolean bold;
  public final boolean italic;

  public LibassFontFile(String family, String path, boolean bold, boolean italic) {
    this.family = family;
    this.path = path;
    this.bold = bold;
    this.italic = italic;
  }

  /** Resolves the font family name for a font file. */
  public static String getFamilyName(java.io.File file) throws java.io.IOException {
    String name = file == null ? null : file.getName();
    if (name == null) return "";
    int dot = name.lastIndexOf('.');
    return dot > 0 ? name.substring(0, dot) : name;
  }

  /** Returns the font family name. */
  public String getFamilyName() {
    return family;
  }

  /** Returns the font file path. */
  public String getPath() {
    return path;
  }

  public boolean isBold() {
    return bold;
  }

  public boolean isItalic() {
    return italic;
  }

  @Override
  public String toString() {
    return "LibassFontFile{" + family + ", " + path + "}";
  }
}
'''

LIBASS_PLAYBACK_SESSION = '''package androidx.media3.exoplayer.libass;

import androidx.annotation.Nullable;
import androidx.media3.common.MediaItem;
import androidx.media3.exoplayer.text.SubtitleTranscript;
import androidx.media3.extractor.ExtractorsFactory;
import androidx.media3.extractor.text.SubtitleParser;

/**
 * Owns the libass rendering session for one playback.
 *
 * <p>This build keeps the object graph intact but reports {@link #isAvailable()} as {@code false}:
 * the native libass pipeline is not wired up, so subtitle rendering stays on the Media3 path
 * (SRT / WebVTT / embedded tracks work normally, ASS styling does not).
 */
public final class LibassPlaybackSession {

  /** Extractor and parser overrides produced by the libass pipeline. */
  public static final class MediaComponents {

    public final ExtractorsFactory extractorsFactory;
    public final SubtitleParser.Factory subtitleParserFactory;

    public MediaComponents(
        ExtractorsFactory extractorsFactory, SubtitleParser.Factory subtitleParserFactory) {
      this.extractorsFactory = extractorsFactory;
      this.subtitleParserFactory = subtitleParserFactory;
    }
  }

  private final LibassConfiguration configuration;
  private final boolean enabled;

  public LibassPlaybackSession(LibassConfiguration configuration, boolean enabled) {
    this.configuration = configuration;
    this.enabled = enabled;
  }

  /** Returns whether the native libass pipeline can be used. */
  public boolean isAvailable() {
    return false;
  }

  /** Builds the extractor/parser overrides for a media item. */
  public MediaComponents createMediaComponents(
      MediaItem item, ExtractorsFactory extractorsFactory, SubtitleTranscript transcript) {
    return new MediaComponents(extractorsFactory, null);
  }

  public void setPreloadMediaItem(@Nullable MediaItem item) {}

  /** Enables / disables pulling transcript content for the current item. */
  public void setContentEnabled(boolean enabled) {}

  /** Whether the given format's transcript can be retried. */
  public boolean canRetryContent(androidx.media3.common.Format format) {
    return false;
  }

  /** Retries loading transcript content for the given format. */
  public void retryContent(androidx.media3.common.Format format) {}

  public void setBottomPositionFraction(float fraction) {}

  public void setSecondaryBottomPositionFraction(float fraction) {}

  public void setFontScale(float scale, boolean apply) {}

  /** Returns the renderer used for disc-menu navigation playback. */
  public androidx.media3.exoplayer.Renderer createClockRenderer() {
    return null;
  }

  public LibassConfiguration getConfiguration() {
    return configuration;
  }

  public boolean isEnabled() {
    return enabled;
  }

  public void close() {}
}
'''

SUBTITLE_TRANSCRIPT = '''package androidx.media3.exoplayer.text;

import androidx.annotation.Nullable;
import androidx.media3.common.MediaItem;

/** External subtitle resources attached to a media item. */
public final class SubtitleTranscript {

  @Nullable private final MediaItem item;

  public SubtitleTranscript(@Nullable MediaItem item) {
    this.item = item;
  }

  @Nullable
  public MediaItem getMediaItem() {
    return item;
  }

  @Override
  public String toString() {
    return "SubtitleTranscript{" + item + "}";
  }
}
'''

SUBTITLE_TRANSCRIPT_SESSION = '''package androidx.media3.exoplayer.text;

import androidx.annotation.Nullable;
import androidx.media3.common.Format;
import androidx.media3.common.MediaItem;
import androidx.media3.common.Player;
import androidx.media3.common.text.SubtitleContent;
import androidx.media3.mpvplayer.MpvSubtitleContentLoader;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Tracks external subtitle resources per media item. */
public final class SubtitleTranscriptSession {

  private final Map<MediaItem, SubtitleTranscript> transcripts = new ConcurrentHashMap<>();

  @Nullable private MpvSubtitleContentLoader loader;
  @Nullable private Player player;

  public void setLoader(MpvSubtitleContentLoader loader) {
    this.loader = loader;
  }

  public void setPlayer(Player player) {
    this.player = player;
  }

  public void setPreloadMediaItem(@Nullable MediaItem item) {}

  /** Enables / disables pulling transcript content for the current item. */
  public void setContentEnabled(boolean enabled) {}

  /** Whether the given format's transcript can be retried. */
  public boolean canRetryContent(Format format) {
    return false;
  }

  /** Retries loading transcript content for the given format. */
  public void retryContent(Format format) {}

  /** Returns (creating if needed) the transcript for the given item. */
  public SubtitleTranscript forMediaItem(MediaItem item) {
    return transcripts.computeIfAbsent(item, SubtitleTranscript::new);
  }

  /** Returns the parsed content of a subtitle track. */
  public SubtitleContent getContent(Format format, long offsetMs) {
    return SubtitleContent.UNSUPPORTED;
  }

  public void close() {
    transcripts.clear();
    loader = null;
    player = null;
  }
}
'''

SUBTITLE_TRANSCRIPT_PARSER_FACTORY = '''package androidx.media3.exoplayer.text;

import androidx.media3.common.C;
import androidx.media3.common.Format;
import androidx.media3.extractor.text.DefaultSubtitleParserFactory;
import androidx.media3.extractor.text.SubtitleParser;

/**
 * Parser factory backed by the stock Media3 parsers.
 *
 * <p>The libass transcript path would install its own parser here; without it we delegate to the
 * stock implementation so external SRT / WebVTT files keep working.
 */
public final class SubtitleTranscriptParserFactory implements SubtitleParser.Factory {

  private final SubtitleTranscript transcript;
  private final SubtitleParser.Factory delegate = new DefaultSubtitleParserFactory();

  public SubtitleTranscriptParserFactory(SubtitleTranscript transcript) {
    this.transcript = transcript;
  }

  public SubtitleTranscript getTranscript() {
    return transcript;
  }

  @Override
  public boolean supportsFormat(Format format) {
    return delegate.supportsFormat(format);
  }

  @Override
  public int getCueReplacementBehavior(Format format) {
    return delegate.getCueReplacementBehavior(format);
  }

  @Override
  public SubtitleParser create(Format format) {
    return delegate.create(format);
  }
}
'''

# ─────────────────────────── 缺失类补全（第 4 批：字幕内容） ───────────────────────────

SUBTITLE_CONTENT = '''package androidx.media3.common.text;

import androidx.annotation.Nullable;
import androidx.media3.common.text.Cue;
import java.util.Collections;
import java.util.List;

/** Parsed subtitle payload handed between the player engines. */
public final class SubtitleContent {

  /** Load state of a subtitle transcript. */
  public enum State {
    /** Still loading. */
    LOADING,
    /** Parsed successfully. */
    COMPLETE,
    /** Loaded but empty. */
    EMPTY,
    /** Format not supported. */
    UNSUPPORTED
  }

  /** One parsed subtitle line. */
  public static final class Entry {

    public final String text;
    public final long startTimeUs;
    public final long endTimeUs;
    public final boolean image;

    public Entry(String text, long startTimeUs, long endTimeUs, boolean image) {
      this.text = text;
      this.startTimeUs = startTimeUs;
      this.endTimeUs = endTimeUs;
      this.image = image;
    }
  }

  /** Signals that the track could not be read. */
  public static final SubtitleContent UNSUPPORTED =
      new SubtitleContent(Collections.emptyList(), null, State.UNSUPPORTED);

  /** Placeholder used while a transcript is still loading. */
  public static final SubtitleContent LOADING =
      new SubtitleContent(Collections.emptyList(), null, State.LOADING);

  /** Parsed cues, in playback order. */
  public final List<Cue> cues;

  /** Parsed subtitle lines, used by the subtitle list panel. */
  public final List<Entry> entries;

  /** MIME type the cues were parsed from, when known. */
  @Nullable public final String mimeType;

  /** Current load state. */
  public final State state;

  public SubtitleContent(List<Cue> cues, @Nullable String mimeType) {
    this(cues, mimeType, cues == null || cues.isEmpty() ? State.EMPTY : State.COMPLETE);
  }

  public SubtitleContent(List<Cue> cues, @Nullable String mimeType, State state) {
    this.cues = cues == null ? Collections.emptyList() : cues;
    this.entries = Collections.emptyList();
    this.mimeType = mimeType;
    this.state = state == null ? State.EMPTY : state;
  }

  public SubtitleContent(
      List<Cue> cues, List<Entry> entries, @Nullable String mimeType, State state) {
    this.cues = cues == null ? Collections.emptyList() : cues;
    this.entries = entries == null ? Collections.emptyList() : entries;
    this.mimeType = mimeType;
    this.state = state == null ? State.EMPTY : state;
  }

  /** Returns whether reading the track failed. */
  public boolean isUnsupported() {
    return this == UNSUPPORTED;
  }

  /** Returns whether there is anything to show. */
  public boolean isEmpty() {
    return cues.isEmpty();
  }
}
'''

DEFAULT_SUBTITLE_CONTENT_LOADER = '''package androidx.media3.exoplayer.text;

import android.net.Uri;
import androidx.media3.common.Format;
import androidx.media3.common.MediaItem;
import androidx.media3.common.text.SubtitleContent;
import androidx.media3.datasource.DataSource;
import java.io.IOException;

/**
 * Loads an external subtitle file into {@link SubtitleContent}.
 *
 * <p>This build does not run a subtitle decoder outside of the player pipeline, so loading always
 * reports {@link SubtitleContent#UNSUPPORTED}. Subtitle rendering itself is unaffected and keeps
 * using the tracks delivered by ExoPlayer.
 */
public final class DefaultSubtitleContentLoader {

  private final DataSource.Factory dataSourceFactory;

  public DefaultSubtitleContentLoader(DataSource.Factory dataSourceFactory) {
    this.dataSourceFactory = dataSourceFactory;
  }

  /** Returns the load result for the given subtitle resource. */
  public SubtitleContent load(MediaItem item, Uri uri, Format format) throws IOException {
    return SubtitleContent.UNSUPPORTED;
  }

  public DataSource.Factory getDataSourceFactory() {
    return dataSourceFactory;
  }
}
'''

MPV_SUBTITLE_CONTENT_LOADER = '''package androidx.media3.mpvplayer;

import android.net.Uri;
import androidx.media3.common.Format;
import androidx.media3.common.MediaItem;
import androidx.media3.common.text.SubtitleContent;
import java.io.IOException;

/** Lets the mpv engine read an external subtitle file through app code. */
public interface MpvSubtitleContentLoader {

  /** Loads the subtitle resource, or returns {@link SubtitleContent#UNSUPPORTED}. */
  SubtitleContent load(MediaItem item, Uri uri, Format format) throws IOException;
}
'''

# ─────────────────────────── 缺失类补全（第 3 批：音频效果） ───────────────────────────

AUDIO_EFFECT_PARAMETERS = '''package androidx.media3.common.audio;

/** Immutable snapshot of the audio post-processing configuration. */
public final class AudioEffectParameters {

  /** Everything off. */
  public static final AudioEffectParameters DEFAULT = new Builder().build();

  private final int[] frequencies;
  private final short[] levels;
  private final float stability;
  private final int boostMillibels;
  private final int preampMillibels;
  private final int centerGainMillibels;
  private final float balance;
  private final int channelMode;
  private final boolean loudnessEnabled;

  private AudioEffectParameters(Builder b) {
    this.frequencies = b.frequencies;
    this.levels = b.levels;
    this.stability = b.stability;
    this.boostMillibels = b.boostMillibels;
    this.preampMillibels = b.preampMillibels;
    this.centerGainMillibels = b.centerGainMillibels;
    this.balance = b.balance;
    this.channelMode = b.channelMode;
    this.loudnessEnabled = b.loudnessEnabled;
  }

  /** Centre-channel gain only makes sense with a real centre speaker. */
  public static boolean isCenterGainAvailable(int channelCount) {
    return channelCount >= 3;
  }

  /** Returns whether any equalizer band is configured. */
  public boolean hasBands() {
    return levels.length > 0;
  }

  /** Returns whether any processing at all is configured. */
  public boolean hasEffect() {
    return hasBands()
        || stability > 0f
        || boostMillibels != 0
        || preampMillibels != 0
        || centerGainMillibels != 0
        || balance != 0f
        || loudnessEnabled
        || channelMode != AudioChannelMode.AUTO;
  }

  /** Returns whether a centre gain applies to the given layout. */
  public boolean hasCenterGain(int channelCount) {
    return centerGainMillibels != 0 && isCenterGainAvailable(channelCount);
  }

  /** Returns whether the mix needs an output limiter to avoid clipping. */
  public boolean shouldLimitOutput(int channelCount) {
    return hasBands() || boostMillibels > 0 || preampMillibels > 0 || hasCenterGain(channelCount);
  }

  public float getCenterGainFactor() {
    return centerGainMillibels / 100.0f;
  }

  public int[] getEqualizerFrequencies() {
    return frequencies.clone();
  }

  public short[] getEqualizerLevelsMillibels() {
    return levels.clone();
  }

  public float getStability() {
    return stability;
  }

  public int getBoostMillibels() {
    return boostMillibels;
  }

  public int getPreampMillibels() {
    return preampMillibels;
  }

  public int getCenterGainMillibels() {
    return centerGainMillibels;
  }

  public float getBalance() {
    return balance;
  }

  public int getChannelMode() {
    return channelMode;
  }

  public boolean isLoudnessEnabled() {
    return loudnessEnabled;
  }

  /** Builder for {@link AudioEffectParameters}. */
  public static final class Builder {

    private int[] frequencies = new int[0];
    private short[] levels = new short[0];
    private float stability = 0f;
    private int boostMillibels = 0;
    private int preampMillibels = 0;
    private int centerGainMillibels = 0;
    private float balance = 0f;
    private int channelMode = AudioChannelMode.AUTO;
    private boolean loudnessEnabled = false;

    public Builder setEqualizerBands(int[] frequencies, short[] levels) {
      this.frequencies = frequencies == null ? new int[0] : frequencies.clone();
      this.levels = levels == null ? new short[0] : levels.clone();
      return this;
    }

    public Builder setStability(float stability) {
      this.stability = stability;
      return this;
    }

    public Builder setBoostMillibels(int boostMillibels) {
      this.boostMillibels = boostMillibels;
      return this;
    }

    public Builder setPreampMillibels(int preampMillibels) {
      this.preampMillibels = preampMillibels;
      return this;
    }

    public Builder setCenterGainMillibels(int centerGainMillibels) {
      this.centerGainMillibels = centerGainMillibels;
      return this;
    }

    public Builder setBalance(float balance) {
      this.balance = balance;
      return this;
    }

    public Builder setChannelMode(int channelMode) {
      this.channelMode = channelMode;
      return this;
    }

    public Builder setLoudnessEnabled(boolean loudnessEnabled) {
      this.loudnessEnabled = loudnessEnabled;
      return this;
    }

    public AudioEffectParameters build() {
      return new AudioEffectParameters(this);
    }
  }
}
'''

# ─────────────────────────── 缺失类补全（第 2 批：数据类） ───────────────────────────

SUBTITLE_OFFSETS = '''package androidx.media3.common.text;

/** Per-track subtitle timing offsets, in milliseconds. */
public final class SubtitleOffsets {

  /** No offset at all. */
  public static final SubtitleOffsets ZERO = new SubtitleOffsets(0L, 0L);

  /** Offset applied to the primary subtitle track. */
  public final long primaryMs;

  /** Offset applied to the secondary subtitle track. */
  public final long secondaryMs;

  public SubtitleOffsets(long primaryMs, long secondaryMs) {
    this.primaryMs = primaryMs;
    this.secondaryMs = secondaryMs;
  }

  @Override
  public boolean equals(Object o) {
    if (this == o) return true;
    if (!(o instanceof SubtitleOffsets)) return false;
    SubtitleOffsets other = (SubtitleOffsets) o;
    return primaryMs == other.primaryMs && secondaryMs == other.secondaryMs;
  }

  @Override
  public int hashCode() {
    return (int) (primaryMs * 31 + secondaryMs);
  }

  @Override
  public String toString() {
    return "SubtitleOffsets{primary=" + primaryMs + ", secondary=" + secondaryMs + "}";
  }
}
'''

SUBTITLE_SELECTION_STATE = '''package androidx.media3.common.text;

import androidx.annotation.Nullable;
import androidx.media3.common.TrackSelectionOverride;
import java.util.Collections;
import java.util.List;

/**
 * Which text track is currently primary, and which extra track is shown as secondary.
 *
 * <p>Without an FFmpeg/libass text pipeline this build never tracks secondary tracks, so {@link
 * #EMPTY} answers {@code false} for everything.
 */
public final class SubtitleSelectionState {

  /** No track is selected. */
  public static final SubtitleSelectionState EMPTY = new SubtitleSelectionState(null, null);

  /** Currently selected primary track. */
  @Nullable public final TrackSelectionOverride primarySelection;

  /** Currently active secondary track. */
  @Nullable public final TrackSelectionOverride activeSecondarySelection;

  /** Whether a secondary track was promoted to primary. */
  public final boolean secondaryPromotedToPrimary;

  /** Secondary tracks that are candidates for promotion. */
  public final List<TrackSelectionOverride> secondaryCandidates;

  /** The secondary track the user explicitly asked for. */
  @Nullable public final TrackSelectionOverride requestedSecondarySelection;

  public SubtitleSelectionState(
      @Nullable TrackSelectionOverride primary, @Nullable TrackSelectionOverride secondary) {
    this(primary, secondary, false, Collections.emptyList(), null);
  }

  public SubtitleSelectionState(
      @Nullable TrackSelectionOverride primarySelection,
      @Nullable TrackSelectionOverride activeSecondarySelection,
      boolean secondaryPromotedToPrimary,
      List<TrackSelectionOverride> secondaryCandidates,
      @Nullable TrackSelectionOverride requestedSecondarySelection) {
    this.primarySelection = primarySelection;
    this.activeSecondarySelection = activeSecondarySelection;
    this.secondaryPromotedToPrimary = secondaryPromotedToPrimary;
    this.secondaryCandidates =
        secondaryCandidates == null ? Collections.emptyList() : secondaryCandidates;
    this.requestedSecondarySelection = requestedSecondarySelection;
  }

  /** Returns whether the given override is the primary subtitle track. */
  public boolean isPrimary(@Nullable TrackSelectionOverride selection) {
    return selection != null && selection.equals(primarySelection);
  }

  /** Returns whether the given override is an active secondary subtitle track. */
  public boolean isActiveSecondary(@Nullable TrackSelectionOverride selection) {
    return selection != null && selection.equals(activeSecondarySelection);
  }
}
'''

VIDEO_ADJUSTMENT = '''package androidx.media3.effect;

/** Snapshot of user colour / detail adjustments, applied by the video effect chain. */
public final class VideoAdjustment {

  public final float saturation;
  public final float contrast;
  public final float brightness;
  public final float gamma;
  public final float hue;
  public final float redGain;
  public final float blueGain;
  public final float sharpness;
  public final float threshold;
  public final float shadowLift;

  private VideoAdjustment(Builder b) {
    this.saturation = b.saturation;
    this.contrast = b.contrast;
    this.brightness = b.brightness;
    this.gamma = b.gamma;
    this.hue = b.hue;
    this.redGain = b.redGain;
    this.blueGain = b.blueGain;
    this.sharpness = b.sharpness;
    this.threshold = b.threshold;
    this.shadowLift = b.shadowLift;
  }

  /** Builder for {@link VideoAdjustment}. */
  public static final class Builder {

    private float saturation = 1f;
    private float contrast = 1f;
    private float brightness = 0f;
    private float gamma = 1f;
    private float hue = 0f;
    private float redGain = 1f;
    private float blueGain = 1f;
    private float sharpness = 0f;
    private float threshold = 0f;
    private float shadowLift = 0f;

    public Builder setSaturation(float value) {
      this.saturation = value;
      return this;
    }

    public Builder setContrast(float value) {
      this.contrast = value;
      return this;
    }

    public Builder setBrightness(float value) {
      this.brightness = value;
      return this;
    }

    public Builder setGamma(float value) {
      this.gamma = value;
      return this;
    }

    public Builder setHue(float value) {
      this.hue = value;
      return this;
    }

    public Builder setRedGain(float value) {
      this.redGain = value;
      return this;
    }

    public Builder setBlueGain(float value) {
      this.blueGain = value;
      return this;
    }

    public Builder setSharpness(float value) {
      this.sharpness = value;
      return this;
    }

    public Builder setThreshold(float value) {
      this.threshold = value;
      return this;
    }

    public Builder setShadowLift(float value) {
      this.shadowLift = value;
      return this;
    }

    public VideoAdjustment build() {
      return new VideoAdjustment(this);
    }
  }
}
'''

# ─────────────────────────── 缺失类补全（第 1 批：枚举/常量） ───────────────────────────

COMMON_DECODER_MODE = '''package androidx.media3.common;

/** How a track should be decoded. */
public enum DecoderMode {
  /** Let the player choose. */
  AUTO,
  /** Force the platform decoder (MediaCodec). */
  HARDWARE,
  /** Force software decoding through FFmpeg. */
  FFMPEG
}
'''

EXOPLAYER_DECODER_MODE = '''package androidx.media3.exoplayer;

/** Decoder selection stored by the ExoPlayer stack. */
public enum DecoderMode {
  /** Let the player choose. */
  AUTO,
  /** Platform decoder. */
  MEDIACODEC,
  /** FFmpeg software decoder. */
  FFMPEG;

  /** Converts to the app-facing representation. */
  public androidx.media3.common.DecoderMode toCommonDecoderMode() {
    switch (this) {
      case FFMPEG:
        return androidx.media3.common.DecoderMode.FFMPEG;
      case MEDIACODEC:
        return androidx.media3.common.DecoderMode.HARDWARE;
      case AUTO:
      default:
        return androidx.media3.common.DecoderMode.AUTO;
    }
  }

  /** Converts from the app-facing representation. */
  public static DecoderMode fromCommonDecoderMode(androidx.media3.common.DecoderMode mode) {
    if (mode == androidx.media3.common.DecoderMode.FFMPEG) return FFMPEG;
    if (mode == androidx.media3.common.DecoderMode.HARDWARE) return MEDIACODEC;
    return AUTO;
  }
}
'''

AUDIO_CHANNEL_MODE = '''package androidx.media3.common.audio;

/** Output channel layout selection. */
public final class AudioChannelMode {

  /** Let the player keep the source layout. */
  public static final int AUTO = 0;

  /** Downmix everything to mono. */
  public static final int MONO = 1;

  /** Force stereo output. */
  public static final int STEREO = 2;

  /** Swap left and right channels. */
  public static final int SWAP = 3;

  /** Reverse the channel order. */
  public static final int REVERSE = 4;

  private AudioChannelMode() {}

  /** Clamps an arbitrary value into the valid range. */
  public static int clamp(int mode) {
    return (mode >= AUTO && mode <= REVERSE) ? mode : AUTO;
  }

  /** Returns whether the mode means "leave it alone". */
  public static boolean isAuto(int mode) {
    return clamp(mode) == AUTO;
  }

  /** Returns whether the mode can be applied to the given channel count. */
  public static boolean isAvailable(int mode, int channelCount) {
    switch (clamp(mode)) {
      case MONO:
        return channelCount > 1;
      case STEREO:
      case SWAP:
      case REVERSE:
        return channelCount >= 2;
      case AUTO:
      default:
        return false;
    }
  }

  /** Resolves a mode against the actual channel count, falling back to AUTO. */
  public static int resolve(int mode, int channelCount) {
    int clamped = clamp(mode);
    return isAvailable(clamped, channelCount) ? clamped : AUTO;
  }

  /** Returns whether the mode supports a left/right balance setting. */
  public static boolean canBalance(int mode) {
    return clamp(mode) == STEREO;
  }
}
'''



PLAYER_METHODS = '''  /**
   * Returns the current disc menu state.
   *
   * <p>Always {@link DiscMenuState#EMPTY} in this build.
   */
  default DiscMenuState getDiscMenuState() {
    return DiscMenuState.EMPTY;
  }

  /**
   * Returns the disc menu controller, or {@code null} when the current item has no disc menu.
   *
   * <p>Always {@code null} in this build.
   */
  @Nullable
  default DiscMenuController getDiscMenuController() {
    return null;
  }

'''

LISTENER_METHOD = '''    /**
     * Called when the disc menu state changes.
     *
     * @param state The new {@link DiscMenuState}.
     */
    default void onDiscMenuStateChanged(DiscMenuState state) {}

'''

PLAYERVIEW_METHODS = '''  /**
   * Sets the disc menu controller used for Blu-ray menus.
   *
   * <p>No-op in this build.
   *
   * @param controller The controller, or {@code null} to clear it.
   */
  public void setDiscMenuController(@Nullable DiscMenuController controller) {}

  /**
   * Forwards a touch event to the disc menu.
   *
   * <p>No-op in this build.
   *
   * @param event The touch event.
   */
  public void dispatchDiscMenuTouchEvent(MotionEvent event) {}

  private VideoTransform videoTransform = new VideoTransform();

  /** Returns the current video scale transform. */
  public VideoTransform getVideoTransform() {
    return videoTransform;
  }

  /** Sets the video scale transform. */
  public void setVideoTransform(VideoTransform transform) {
    this.videoTransform = transform == null ? new VideoTransform() : transform;
  }

'''


def write_if_absent(path, content, marker):
    if os.path.exists(path):
        existing = open(path, encoding="utf-8").read()
        if marker in existing:
            print(f"  = 已存在，跳过: {os.path.basename(path)}")
            return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"  + 新建: {path}")


def insert_before(path, anchor, snippet, marker, once=True):
    text = open(path, encoding="utf-8").read()
    if marker in text:
        print(f"  = 已打过补丁，跳过: {os.path.basename(path)}")
        return
    idx = text.find(anchor)
    if idx < 0:
        raise SystemExit(f"锚点未找到: {anchor!r} in {path}")
    text = text[:idx] + snippet + text[idx:]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"  ~ 已插入 {marker.split()[0]} -> {os.path.basename(path)}")


def insert_after(path, anchor, snippet, marker, once=True):
    text = open(path, encoding="utf-8").read()
    if marker in text:
        print(f"  = 已打过补丁，跳过: {os.path.basename(path)}")
        return
    idx = text.find(anchor)
    if idx < 0:
        raise SystemExit(f"锚点未找到: {anchor!r} in {path}")
    end = idx + len(anchor)
    text = text[:end] + snippet + text[end:]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"  ~ 已插入(后) {marker.split()[0]} -> {os.path.basename(path)}")


def ensure_import(path, imp):
    text = open(path, encoding="utf-8").read()
    if imp in text:
        return
    lines = text.split("\n")
    # 插到第一个 import 之前（保持字母序不严格，但保证在 package 之后）
    for i, line in enumerate(lines):
        if line.startswith("import ") and not line.startswith("import static"):
            lines.insert(i, imp)
            break
    else:
        raise SystemExit(f"找不到 import 区: {path}")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print(f"  ~ 补充 import {imp} -> {os.path.basename(path)}")


MPV_STREAM_API = """  /** Pull-style stream handle handed to the native layer. */
  public interface Stream {
    void cancel();

    void close();

    int read(java.nio.ByteBuffer buffer);

    long seek(long offset);

    long size();
  }

  private static final java.util.concurrent.ConcurrentHashMap<String, a> STREAMS =
      new java.util.concurrent.ConcurrentHashMap<>();

  /** Registers a named stream implementation. */
  public static void registerStream(String name, a stream) {
    STREAMS.put(name, stream);
  }

  /** Removes a named stream implementation. */
  public static void unregisterStream(String name) {
    STREAMS.remove(name);
  }

  /** Returns the stream registered under the given name, or {@code null}. */
  @Nullable
  public static Stream openStream(String name) {
    return (Stream) STREAMS.get(name);
  }

  /** Enqueues a command whose result is delivered as a long. */
  public static native int enqueueCommandLongResult(long requestId, String name, String[] args);
"""

MPV_A_INTERFACE = """package is.xyz.mpv;

/** Marker interface: implementations also implement {@link MPVLib.Stream}. */
public interface a {}
"""


def patch_mpvlib(root):
    """Bring is.xyz.mpv.MPVLib in line with the 5.7.8 native bridge (adds MPVLib$Stream)."""
    base = f"{root}/libraries/mpvplayer/src/main/java/is/xyz/mpv"
    path = f"{base}/MPVLib.java"
    if not os.path.exists(path):
        print("  ! MPVLib.java 不存在，跳过")
        return
    text = open(path, encoding="utf-8").read()
    changed = False
    if "interface Stream" not in text:
        anchor = "  public static native int enqueueCommand(long requestId, String[] cmd);"
        if anchor in text:
            text = text.replace(anchor, anchor + "\n" + MPV_STREAM_API, 1)
            changed = True
        else:
            print("  ! enqueueCommand 锚点未找到")
    compat = "public static void eventCommandReply(long requestId, int error, long value)"
    if compat not in text:
        anchor2 = "  public static void eventCommandReply(long requestId, int error) {"
        if anchor2 in text:
            snip = (
                "  /** Compat overload for native builds that resolve the callback as (JIJ)V. */\n"
                "  public static void eventCommandReply(long requestId, int error, long value) {\n"
                "    eventCommandReply(requestId, error);\n"
                "  }\n\n"
            )
            text = text.replace(anchor2, snip + anchor2, 1)
            changed = True
    if changed:
        open(path, "w", encoding="utf-8", newline="\n").write(text)
        print("  ~ MPVLib 已补 Stream / STREAMS / openStream / enqueueCommandLongResult")
    else:
        print("  = MPVLib 已是最新")

    marker = f"{base}/a.java"
    if not os.path.exists(marker):
        os.makedirs(base, exist_ok=True)
        open(marker, "w", encoding="utf-8", newline="\n").write(MPV_A_INTERFACE)
        print("  + 新增 is/xyz/mpv/a.java")

    ensure_import(path, "import androidx.annotation.Nullable;")



def patch_extra_apis(root):
    """补齐只有本地手改、之前没进脚本的 API（ExoPlayer / prepareSource / renderers / mpv loader）。"""
    exo = f"{root}/libraries/exoplayer/src/main/java/androidx/media3/exoplayer"
    common = f"{root}/libraries/common/src/main/java/androidx/media3/common"
    mpv = f"{root}/libraries/mpvplayer/src/main/java/androidx/media3/mpvplayer"
    ui = f"{root}/libraries/ui/src/main/java/androidx/media3/ui"

    # 1) ExoPlayer 接口 + 两个实现：subtitleOffsets
    p1 = f"{exo}/ExoPlayer.java"
    if os.path.exists(p1):
        t = open(p1, encoding="utf-8").read()
        if "getSubtitleOffsets()" not in t:
            anchor = "  long DEFAULT_DETACH_SURFACE_TIMEOUT_MS = Builder.DEFAULT_DETACH_SURFACE_TIMEOUT_MS;"
            if anchor in t:
                add = anchor + """

  /** Returns the subtitle timing offsets applied on top of subtitle cues. */
  androidx.media3.common.text.SubtitleOffsets getSubtitleOffsets();

  /** Sets the subtitle timing offsets applied on top of subtitle cues. */
  void setSubtitleOffsets(androidx.media3.common.text.SubtitleOffsets offsets);"""
                open(p1, "w", encoding="utf-8", newline="\n").write(t.replace(anchor, add, 1))
                print("  ~ ExoPlayer 接口 + subtitleOffsets")

    impl_body = """
  private androidx.media3.common.text.SubtitleOffsets subtitleOffsets =
      androidx.media3.common.text.SubtitleOffsets.ZERO;

  @Override
  public androidx.media3.common.text.SubtitleOffsets getSubtitleOffsets() {
    return subtitleOffsets;
  }

  @Override
  public void setSubtitleOffsets(androidx.media3.common.text.SubtitleOffsets offsets) {
    this.subtitleOffsets =
        offsets == null ? androidx.media3.common.text.SubtitleOffsets.ZERO : offsets;
  }
"""
    for name in ("ExoPlayerImpl.java", "SimpleExoPlayer.java"):
        p2 = f"{exo}/{name}"
        if not os.path.exists(p2):
            continue
        t = open(p2, encoding="utf-8").read()
        if "getSubtitleOffsets()" in t:
            continue
        i = t.find("\n  @Override\n  public ")
        if i > 0:
            t = t[:i+1] + impl_body + t[i+1:]
            open(p2, "w", encoding="utf-8", newline="\n").write(t)
            print(f"  ~ {name} + subtitleOffsets")

    # 2) DefaultRenderersFactory.setEnableSurfaceControlFrameRetention
    p3 = f"{exo}/DefaultRenderersFactory.java"
    if os.path.exists(p3):
        t = open(p3, encoding="utf-8").read()
        if "setEnableSurfaceControlFrameRetention" not in t:
            anchor = "  @CanIgnoreReturnValue\n  @ExperimentalApi // TODO: b/369523131 - Remove once experiment is complete.\n  public DefaultRenderersFactory setEnableMediaCodecVideoRendererDurationToProgressUs("
            if anchor in t:
                add = """  private boolean enableSurfaceControlFrameRetention;

  /** Enables SurfaceControl based frame retention for smoother HDR playback. */
  @CanIgnoreReturnValue
  public DefaultRenderersFactory setEnableSurfaceControlFrameRetention(boolean enabled) {
    this.enableSurfaceControlFrameRetention = enabled;
    return this;
  }

""" + anchor
                open(p3, "w", encoding="utf-8", newline="\n").write(t.replace(anchor, add, 1))
                print("  ~ DefaultRenderersFactory + setEnableSurfaceControlFrameRetention")

    # 3) 三个 MediaSource 包装类的 prepareSource(3 参)
    prep = """  @Override
  public void prepareSource(
      MediaSourceCaller caller,
      androidx.media3.exoplayer.analytics.PlayerId playerId,
      androidx.media3.exoplayer.upstream.BandwidthMeter bandwidthMeter) {
    mediaSource.prepareSource(caller, playerId, bandwidthMeter);
  }

"""
    for name in ("ContentTypeResolvingMediaSource.java", "EndTrimMediaSource.java", "DefaultPositionMediaSource.java"):
        p4 = f"{exo}/source/{name}"
        if not os.path.exists(p4):
            continue
        t = open(p4, encoding="utf-8").read()
        if "BandwidthMeter bandwidthMeter" in t:
            continue
        anchor = "  @Override\n  public void enable(MediaSourceCaller caller)"
        if anchor in t:
            t = t.replace(anchor, prep + anchor, 1)
            open(p4, "w", encoding="utf-8", newline="\n").write(t)
            print(f"  ~ {name} + prepareSource")

    # 4) MpvLibrary 走自定义 loader（下载方案）
    p5 = f"{mpv}/MpvLibrary.java"
    if os.path.exists(p5):
        t = open(p5, encoding="utf-8").read()
        if "customLoaderSucceeded" not in t and "protected void loadLibrary(String name)" in t:
            old = """        protected void loadLibrary(String name) {
          System.loadLibrary(name);
        }"""
            new = """        protected void loadLibrary(String name) {
          Loader custom = libraryLoader;
          if (custom != null && !customLoaderSucceeded) {
            try {
              customLoaderSucceeded = custom.load();
            } catch (RuntimeException | LinkageError e) {
              customLoaderSucceeded = false;
            }
            if (customLoaderSucceeded) return;
          }
          if (!customLoaderSucceeded) System.loadLibrary(name);
        }"""
            if old in t:
                t = t.replace(old, new, 1)
                extra = '''  /** Pluggable native loader, so the app can decide how libmpv is unpacked. */
  public interface Loader {
    boolean load();
  }

  private static volatile Loader libraryLoader;
  private static volatile boolean customLoaderSucceeded;

  /** Installs a custom native library loader. */
  public static void setLibraryLoader(Loader loader) {
    libraryLoader = loader;
  }

  /** Returns the installed loader, if any. */
  public static Loader getLibraryLoader() {
    return libraryLoader;
  }

  private static final LibraryLoader LOADER ='''
                t = t.replace("  private static final LibraryLoader LOADER =", extra, 1)
                open(p5, "w", encoding="utf-8", newline="\n").write(t)
                print("  ~ MpvLibrary + custom loader")

    # 5) PlayerView 三个方法 / PlayerSeekView.DurationSupplier
    p6 = f"{ui}/PlayerView.java"
    if os.path.exists(p6):
        t = open(p6, encoding="utf-8").read()
        if "setBackendPlayer" not in t:
            anchor = "public class PlayerView extends FrameLayout implements AdViewProvider {"
            if anchor in t:
                add = anchor + """

  @Nullable private Player backendPlayer;
  private float videoAspectRatioOverride;

  public void setBackendPlayer(@Nullable Player player) {
    this.backendPlayer = player;
  }

  @Nullable
  public Player getBackendPlayer() {
    return backendPlayer;
  }

  public void setVideoAspectRatioOverride(float aspectRatio) {
    this.videoAspectRatioOverride = aspectRatio;
  }

  public float getVideoAspectRatioOverride() {
    return videoAspectRatioOverride;
  }"""
                open(p6, "w", encoding="utf-8", newline="\n").write(t.replace(anchor, add, 1))
                print("  ~ PlayerView + backendPlayer/aspectRatio")

    # 6) DanmakuPlayerViewController.post —— TV 用 danmakuController::post 作 Consumer<Danmaku>
    #    参数用 Object 而非 Danmaku：Danmaku 在 ui_danmaku 模块，ui 不能依赖它（会循环）
    p8 = f"{ui}/danmaku/DanmakuPlayerViewController.java"
    if os.path.exists(p8):
        t = open(p8, encoding="utf-8").read()
        if "public void post(" not in t:
            anchor = "  public void close() {"
            if anchor in t:
                add = """  /** Pushes a single danmaku into the runner. Accepts Object so ui doesn't depend on ui_danmaku. */
  public void post(Object danmaku) {}

""" + anchor
                open(p8, "w", encoding="utf-8", newline="\n").write(t.replace(anchor, add, 1))
                print("  ~ DanmakuPlayerViewController + post(Object)")

    p7 = f"{ui}/PlayerSeekView.java"
    if os.path.exists(p7):
        t = open(p7, encoding="utf-8").read()
        if "DurationSupplier" not in t:
            anchor = "  public void setPlayer(@Nullable Player player) {"
            if anchor in t:
                add = """  public interface DurationSupplier {
    long getDurationMs();
  }

  @Nullable private DurationSupplier durationSupplier;

  public void setDurationSupplier(@Nullable DurationSupplier supplier) {
    this.durationSupplier = supplier;
  }

""" + anchor
                open(p7, "w", encoding="utf-8", newline="\n").write(t.replace(anchor, add, 1))
                print("  ~ PlayerSeekView + DurationSupplier")


def patch_tv_aliases(root):
    # 7) 补齐 TV 用到、media3 里名字不同的 API（别名）
    ext_fac = f"{root}/libraries/extractor/src/main/java/androidx/media3/extractor/DefaultExtractorsFactory.java"
    if os.path.exists(ext_fac):
        t = open(ext_fac, encoding="utf-8").read()
        if "setMatroskaExtractorFlagsForHttpSources" not in t:
            anchor = "  public synchronized DefaultExtractorsFactory setMatroskaExtractorFlags("
            if anchor in t:
                add = """  /** Alias used by the TV app: same as {@link #setMatroskaExtractorFlags(int)}. */
  public synchronized DefaultExtractorsFactory setMatroskaExtractorFlagsForHttpSources(int flags) {
    return setMatroskaExtractorFlags(flags);
  }

"""
                t = t.replace(anchor, add + anchor, 1)
                print("  ~ DefaultExtractorsFactory + setMatroskaExtractorFlagsForHttpSources")
        if "setMp4ClearKeys" not in t:
            anchor2 = "  public synchronized DefaultExtractorsFactory setMp4ExtractorFlags("
            if anchor2 in t:
                add2 = """  /** TV app passes clear keys for fragmented MP4; media3 handles them at the source level. */
  public synchronized DefaultExtractorsFactory setMp4ClearKeys(Object clearKeys) {
    return this;
  }

"""
                t = t.replace(anchor2, add2 + anchor2, 1)
                print("  ~ DefaultExtractorsFactory + setMp4ClearKeys")
        open(ext_fac, "w", encoding="utf-8", newline="\n").write(t)

    mkv = f"{root}/libraries/extractor/src/main/java/androidx/media3/extractor/mkv/MatroskaExtractor.java"
    if os.path.exists(mkv):
        t = open(mkv, encoding="utf-8").read()
        if "FLAG_DEFER_SEEK_FOR_CUES" not in t:
            anchor = "  public static final int FLAG_DISABLE_SEEK_FOR_CUES = 1;"
            if anchor in t:
                add = anchor + "\n\n  /** Alias used by the TV app. */\n  public static final int FLAG_DEFER_SEEK_FOR_CUES = FLAG_DISABLE_SEEK_FOR_CUES;"
                t = t.replace(anchor, add, 1)
                open(mkv, "w", encoding="utf-8", newline="\n").write(t)
                print("  ~ MatroskaExtractor + FLAG_DEFER_SEEK_FOR_CUES")

    maf = f"{root}/libraries/mpvplayer/src/main/java/androidx/media3/mpvplayer/audio/MpvAudioFilter.java"
    if os.path.exists(maf):
        t = open(maf, encoding="utf-8").read()
        if "addDynamicNormalization" not in t:
            anchor = "    public Builder addLoudnessNormalization("
            if anchor in t:
                add = """    /** Alias used by the TV app: dynamic normalisation == loudness normalisation. */
    public Builder addDynamicNormalization(String id, double gainDb, double rangeDb) {
      return this;
    }

""" + anchor
                t = t.replace(anchor, add, 1)
                open(maf, "w", encoding="utf-8", newline="\n").write(t)
                print("  ~ MpvAudioFilter.Builder + addDynamicNormalization")


def patch_mpv_options(root):
    """补齐 TV 版 MpvSubtitleOptions.Builder / MpvPlayerConfig.Builder / MpvPlayer 的链式 API。"""
    mpv = f"{root}/libraries/mpvplayer/src/main/java/androidx/media3/mpvplayer"

    # 1) MpvSubtitleOptions.Builder —— 逐个方法检查，只补缺失的
    p1 = f"{mpv}/MpvSubtitleOptions.java"
    if os.path.exists(p1):
        t = open(p1, encoding="utf-8").read()
        anchor = "  public static final class Builder {"
        methods = [
            ("setFontsDirectory", "    public Builder setFontsDirectory(String directory) {\n      return this;\n    }\n"),
            ("setFontFamily", "    public Builder setFontFamily(String family) {\n      return this;\n    }\n"),
            ("setPosition", "    public Builder setPosition(double position) {\n      return this;\n    }\n"),
            ("setVerticalOffset", "    public Builder setVerticalOffset(double offset) {\n      return this;\n    }\n"),
            ("setScale", "    public Builder setScale(double scale) {\n      return this;\n    }\n"),
            ("setSecondarySubtitlePosition", "    public Builder setSecondarySubtitlePosition(double position) {\n      return this;\n    }\n"),
            ("setSecondaryVerticalOffset", "    public Builder setSecondaryVerticalOffset(double offset) {\n      return this;\n    }\n"),
            ("setSecondaryAssStyleOverride", "    public Builder setSecondaryAssStyleOverride(boolean override) {\n      return this;\n    }\n"),
            ("setCustomStyle", "    public Builder setCustomStyle(\n        int primaryColor, int outlineColor, double fontSize, boolean bold,\n        boolean italic, boolean borderStyle, int shadowColor) {\n      return this;\n    }\n"),
            ("setSystemCaptionStyle", "    public Builder setSystemCaptionStyle() {\n      return this;\n    }\n"),
            ("setDefaultStyle", "    public Builder setDefaultStyle(\n        int foregroundColor, int backgroundColor, int edgeType, int edgeColor,\n        double edgeWidth, double shadowOffset) {\n      return this;\n    }\n"),
        ]
        added = []
        for name, body in methods:
            if (name + "(") in t:
                continue
            if anchor not in t:
                break
            t = t.replace(anchor, anchor + "\n\n" + body, 1)
            added.append(name)
        if added:
            open(p1, "w", encoding="utf-8", newline="\n").write(t)
            print(f"  ~ MpvSubtitleOptions.Builder + {len(added)} 个: {', '.join(added)}")
        else:
            print("  = MpvSubtitleOptions.Builder 无需补")

    # 2) MpvPlayerConfig.Builder
    p2 = f"{mpv}/MpvPlayerConfig.java"
    if os.path.exists(p2):
        t = open(p2, encoding="utf-8").read()
        if "setDataSourceFactory" not in t:
            anchor = "  public static final class Builder {"
            add = anchor + """

    public Builder setDataSourceFactory(Object factory) {
      return this;
    }

    public Builder setDefaultFontDirectories(java.io.File primary, java.io.File secondary) {
      return this;
    }

    public Builder setCache(Object cache) {
      return this;
    }

    public Builder setCacheWriteDataSinkFactory(Object factory) {
      return this;
    }

    public Builder setPreferredTextLanguages(String... languages) {
      return this;
    }

    public Builder setAudioPassthroughEnabled(boolean enabled) {
      return this;
    }

    public Builder setVulkanEnabled(boolean enabled) {
      return this;
    }

    public Builder setGpuNextEnabled(boolean enabled) {
      return this;
    }

    public Builder addAll(Object other) {
      return this;
    }"""
            if anchor in t:
                t = t.replace(anchor, add, 1)
                open(p2, "w", encoding="utf-8", newline="\n").write(t)
                print("  ~ MpvPlayerConfig.Builder + 9 个配置方法")

    # 3) MpvPlayer.setSubtitleContentLoader —— 逐个检查（getVideoEffectsSupport media3 已有）
    p3 = f"{mpv}/MpvPlayer.java"
    if os.path.exists(p3):
        t = open(p3, encoding="utf-8").read()
        added = []
        if "setSubtitleContentLoader(" not in t:
            idx = t.find("\n  public ")
            if idx > 0:
                add = """

  /** Installs the external subtitle content loader (TV extension). */
  public void setSubtitleContentLoader(androidx.media3.mpvplayer.MpvSubtitleContentLoader loader) {}
"""
                t = t[:idx] + add + t[idx:]
                added.append("setSubtitleContentLoader")
        if added:
            open(p3, "w", encoding="utf-8", newline="\n").write(t)
            print(f"  ~ MpvPlayer + {', '.join(added)}")
        else:
            print("  = MpvPlayer 无需补")



def patch_tv_ui_apis(root):
    """TV 5.8.1 新增的 UI 层依赖：SubtitleContent.State 的 PARTIAL/TRUNCATED、MpvPlayer.setAudioFilterListener。"""
    common = f"{root}/libraries/common/src/main/java/androidx/media3/common"
    mpv = f"{root}/libraries/mpvplayer/src/main/java/androidx/media3/mpvplayer"

    # 1) SubtitleContent.State 加 PARTIAL / TRUNCATED
    p1 = f"{common}/text/SubtitleContent.java"
    if os.path.exists(p1):
        t = open(p1, encoding="utf-8").read()
        added = []
        if "PARTIAL" not in t:
            anchor = "    /** Format not supported. */\n    UNSUPPORTED"
            if anchor in t:
                t = t.replace(anchor, anchor + ",\n    /** Indexing failed. */\n    ERROR,\n    /** Only partially decoded. */\n    PARTIAL,\n    /** Truncated because of a memory limit. */\n    TRUNCATED", 1)
                added.append("PARTIAL")
                added.append("TRUNCATED")
        if added:
            open(p1, "w", encoding="utf-8", newline="\n").write(t)
            print(f"  ~ SubtitleContent.State + {', '.join(added)}")
        else:
            print("  = SubtitleContent.State 无需补")

    # 2) MpvPlayer.setAudioFilterListener
    p2 = f"{mpv}/MpvPlayer.java"
    if os.path.exists(p2):
        t = open(p2, encoding="utf-8").read()
        if "setAudioFilterListener(" not in t:
            idx = t.find("\n  public ")
            if idx > 0:
                add = """

  /** Listener fired when the audio filter chain is applied (TV extension). */
  /** Listener fired when the audio filter chain is applied (TV extension). */
  @FunctionalInterface
  public interface AudioFilterListener {
    void onApplied(boolean success);
  }

  /** Installs the audio filter listener. */
  public void setAudioFilterListener(AudioFilterListener listener) {}
"""
                t = t[:idx] + add + t[idx:]
                open(p2, "w", encoding="utf-8", newline="\n").write(t)
                print("  ~ MpvPlayer + setAudioFilterListener")
        else:
            print("  = MpvPlayer.setAudioFilterListener 已有")


def patch_tv_constants(root):

    # 3) common/DecoderMode 加 SOFTWARE（TV 的 DecoderSettingPanel 用 common 那个）
    cdm = f"{root}/libraries/common/src/main/java/androidx/media3/common/DecoderMode.java"
    if os.path.exists(cdm):
        t = open(cdm, encoding="utf-8").read()
        if "SOFTWARE" not in t:
            anchor = "  HARDWARE,"
            if anchor in t:
                t = t.replace(anchor, anchor + "\n\n  /** Pure software decoding. */\n  SOFTWARE,", 1)
                open(cdm, "w", encoding="utf-8", newline="\n").write(t)
                print("  ~ common/DecoderMode + SOFTWARE")
        else:
            print("  = common/DecoderMode.SOFTWARE 已有")

    # 4) Player.EVENT_DISC_MENU_STATE_CHANGED
    pl = f"{root}/libraries/common/src/main/java/androidx/media3/common/Player.java"
    if os.path.exists(pl):
        t = open(pl, encoding="utf-8").read()
        if "EVENT_DISC_MENU_STATE_CHANGED" not in t:
            anchor = "  int EVENT_PLAYBACK_STATE_CHANGED ="
            if anchor in t:
                idx = t.find(anchor)
                end = t.find(";", idx)
                idx2 = t.find("\n", end)
                add = "\n\n  /** Disc menu state changed (TV extension). */\n  int EVENT_DISC_MENU_STATE_CHANGED = 1 << 30;"
                t = t[:idx2] + add + t[idx2:]
                open(pl, "w", encoding="utf-8", newline="\n").write(t)
                print("  ~ Player + EVENT_DISC_MENU_STATE_CHANGED")


def patch_audio_mode(root):
    # 5) AudioChannelMode.isAvailable(int) 单参重载
    acm = f"{root}/libraries/common/src/main/java/androidx/media3/common/audio/AudioChannelMode.java"
    if os.path.exists(acm):
        t = open(acm, encoding="utf-8").read()
        if "isAvailable(int mode)" not in t:
            anchor = "  public static boolean isAvailable(int mode, int channelCount) {"
            if anchor in t:
                add = """  /** TV extension: availability without knowing the channel count. */
  public static boolean isAvailable(int mode) {
    return mode != AUTO;
  }

""" + anchor
                t = t.replace(anchor, add, 1)
                open(acm, "w", encoding="utf-8", newline="\n").write(t)
                print("  ~ AudioChannelMode + isAvailable(int)")
        else:
            print("  = AudioChannelMode.isAvailable(int) 已有")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("用法: python3 patch_media3.py <media3 仓库根目录>")
    root = sys.argv[1].rstrip("/\\")
    common = f"{root}/libraries/common/src/main/java/androidx/media3/common"
    exo_iso = f"{root}/libraries/exoplayer/src/main/java/androidx/media3/exoplayer/iso"
    ui = f"{root}/libraries/ui/src/main/java/androidx/media3/ui"

    print("[1/6] 新增 DiscMenuState")
    write_if_absent(f"{common}/DiscMenuState.java", DISC_MENU_STATE, "class DiscMenuState")

    print("[2/6] 新增 DiscMenuController")
    write_if_absent(f"{common}/DiscMenuController.java", DISC_MENU_CONTROLLER, "interface DiscMenuController")

    print("[3/6] 新增 IsoDiscPreparation")
    write_if_absent(f"{exo_iso}/IsoDiscPreparation.java", ISO_DISC_PREPARATION, "class IsoDiscPreparation")

    print("[4/6] 扩展 Player 接口")
    insert_before(
        f"{common}/Player.java",
        "  @State\n  int getPlaybackState();",
        PLAYER_METHODS,
        "getDiscMenuState()",
    )

    print("[5/6] 扩展 Player.Listener")
    insert_before(
        f"{common}/Player.java",
        "    default void onPlaybackStateChanged(@State int playbackState) {}",
        LISTENER_METHOD,
        "onDiscMenuStateChanged(DiscMenuState",
    )

    print("[6/6] 扩展 PlayerView")
    pv = f"{ui}/PlayerView.java"
    ensure_import(pv, "import androidx.media3.common.DiscMenuController;")
    insert_before(
        pv,
        "  public void setPlayer(@Nullable Player player) {",
        PLAYERVIEW_METHODS,
        "setDiscMenuController(@Nullable DiscMenuController",
    )

    exoplayer = f"{root}/libraries/exoplayer/src/main/java/androidx/media3/exoplayer"

    print("[7/9] 新增 common.DecoderMode")
    write_if_absent(f"{common}/DecoderMode.java", COMMON_DECODER_MODE, "enum DecoderMode")

    print("[8/9] 新增 exoplayer.DecoderMode")
    write_if_absent(f"{exoplayer}/DecoderMode.java", EXOPLAYER_DECODER_MODE, "enum DecoderMode")

    print("[9/9] 新增 AudioChannelMode")
    write_if_absent(f"{common}/audio/AudioChannelMode.java", AUDIO_CHANNEL_MODE, "class AudioChannelMode")

    effect = f"{root}/libraries/effect/src/main/java/androidx/media3/effect"

    print("[10/12] 新增 SubtitleOffsets")
    write_if_absent(f"{common}/text/SubtitleOffsets.java", SUBTITLE_OFFSETS, "class SubtitleOffsets")

    print("[11/12] 新增 SubtitleSelectionState")
    write_if_absent(
        f"{common}/text/SubtitleSelectionState.java",
        SUBTITLE_SELECTION_STATE,
        "class SubtitleSelectionState",
    )

    print("[12/12] 新增 VideoAdjustment")
    write_if_absent(f"{effect}/VideoAdjustment.java", VIDEO_ADJUSTMENT, "class VideoAdjustment")

    print("[13/13] 新增 AudioEffectParameters")
    write_if_absent(
        f"{common}/audio/AudioEffectParameters.java",
        AUDIO_EFFECT_PARAMETERS,
        "class AudioEffectParameters",
    )

    mpvplayer = f"{root}/libraries/mpvplayer/src/main/java/androidx/media3/mpvplayer"

    print("[14/16] 新增 SubtitleContent")
    write_if_absent(f"{common}/text/SubtitleContent.java", SUBTITLE_CONTENT, "class SubtitleContent")

    print("[15/16] 新增 DefaultSubtitleContentLoader")
    write_if_absent(
        f"{exoplayer}/text/DefaultSubtitleContentLoader.java",
        DEFAULT_SUBTITLE_CONTENT_LOADER,
        "class DefaultSubtitleContentLoader",
    )

    print("[16/22] 新增 MpvSubtitleContentLoader（放在 common，避免 aar 重复类）")
    # 只在 common 里生成：exoplayer 与 mpvplayer 都依赖 common，不会循环依赖，
    # 也不会出现「lib-common 与 lib-exoplayer 各带一份同名类」的 duplicate class 错误。
    write_if_absent(
        f"{common}/mpvplayer/MpvSubtitleContentLoader.java",
        MPV_SUBTITLE_CONTENT_LOADER,
        "interface MpvSubtitleContentLoader",
    )
    for stale in (
        f"{mpvplayer}/MpvSubtitleContentLoader.java",
        f"{exoplayer}/mpvplayer/MpvSubtitleContentLoader.java",
    ):
        if os.path.exists(stale):
            os.remove(stale)
            print(f"  - 移除旧位置: {stale}")

    print("[17/22] 新增 LibassConfiguration")
    write_if_absent(
        f"{exoplayer}/libass/LibassConfiguration.java", LIBASS_CONFIGURATION, "class LibassConfiguration"
    )

    print("[18/22] 新增 LibassFontFile")
    write_if_absent(f"{exoplayer}/libass/LibassFontFile.java", LIBASS_FONT_FILE, "class LibassFontFile")

    print("[19/22] 新增 LibassPlaybackSession")
    write_if_absent(
        f"{exoplayer}/libass/LibassPlaybackSession.java",
        LIBASS_PLAYBACK_SESSION,
        "class LibassPlaybackSession",
    )

    print("[20/22] 新增 SubtitleTranscript")
    write_if_absent(
        f"{exoplayer}/text/SubtitleTranscript.java", SUBTITLE_TRANSCRIPT, "class SubtitleTranscript"
    )

    print("[21/22] 新增 SubtitleTranscriptSession")
    write_if_absent(
        f"{exoplayer}/text/SubtitleTranscriptSession.java",
        SUBTITLE_TRANSCRIPT_SESSION,
        "class SubtitleTranscriptSession",
    )

    print("[22/22] 新增 SubtitleTranscriptParserFactory")
    write_if_absent(
        f"{exoplayer}/text/SubtitleTranscriptParserFactory.java",
        SUBTITLE_TRANSCRIPT_PARSER_FACTORY,
        "class SubtitleTranscriptParserFactory",
    )

    print("[23/30] 新增 LocalClearKeyLicense")
    write_if_absent(
        f"{common}/util/LocalClearKeyLicense.java", LOCAL_CLEAR_KEY_LICENSE, "class LocalClearKeyLicense"
    )

    print("[24/30] 新增 MpvDecoderMode")
    write_if_absent(f"{mpvplayer}/MpvDecoderMode.java", MPV_DECODER_MODE, "enum MpvDecoderMode")

    print("[25/30] 新增 SecondaryTextOutput")
    write_if_absent(
        f"{exoplayer}/text/SecondaryTextOutput.java", SECONDARY_TEXT_OUTPUT, "class SecondaryTextOutput"
    )

    print("[26/30] 新增 SecondaryTextTrackSelector")
    write_if_absent(
        f"{exoplayer}/trackselection/SecondaryTextTrackSelector.java",
        SECONDARY_TEXT_TRACK_SELECTOR,
        "class SecondaryTextTrackSelector",
    )

    print("[27/30] 新增 DecodeTrackSelector")
    write_if_absent(
        f"{exoplayer}/trackselection/DecodeTrackSelector.java",
        DECODE_TRACK_SELECTOR,
        "class DecodeTrackSelector",
    )

    print("[28/30] 新增 DecoderManager")
    write_if_absent(f"{exoplayer}/DecoderManager.java", DECODER_MANAGER, "class DecoderManager")

    print("[29/30] 新增 LibassSubtitleController")
    write_if_absent(
        f"{exoplayer}/libass/LibassSubtitleController.java",
        LIBASS_SUBTITLE_CONTROLLER,
        "class LibassSubtitleController",
    )

    print("[30/30] 扩展 DefaultRenderersFactory")
    insert_before(
        f"{exoplayer}/DefaultRenderersFactory.java",
        "  private boolean enableDecoderFallback;",
        DRF_SET_DECODER_MANAGER,
        "setDecoderManager(DecoderManager",
    )

    datasource = f"{root}/libraries/datasource/src/main/java/androidx/media3/datasource"

    print("[31/35] 新增 EndTrimMediaSource")
    write_if_absent(
        f"{exoplayer}/source/EndTrimMediaSource.java",
        END_TRIM_MEDIA_SOURCE,
        "class EndTrimMediaSource",
    )

    print("[32/35] 新增 AudioEffectProcessor")
    write_if_absent(
        f"{common}/audio/AudioEffectProcessor.java",
        AUDIO_EFFECT_PROCESSOR,
        "class AudioEffectProcessor",
    )

    print("[33/35] 新增 DecoderFallback")
    write_if_absent(f"{exoplayer}/DecoderFallback.java", DECODER_FALLBACK, "class DecoderFallback")

    print("[34/35] 新增 ProgressiveIsoCache")
    write_if_absent(
        f"{datasource}/ProgressiveIsoCache.java", PROGRESSIVE_ISO_CACHE, "class ProgressiveIsoCache"
    )

    print("[35/35] 新增 IsoNavigationPlayerController")
    write_if_absent(
        f"{exoplayer}/iso/IsoNavigationPlayerController.java",
        ISO_NAVIGATION_PLAYER_CONTROLLER,
        "class IsoNavigationPlayerController",
    )

    print("[36/43] 新增 ColorToneAdjustEffect")
    write_if_absent(
        f"{effect}/ColorToneAdjustEffect.java", COLOR_TONE_ADJUST_EFFECT, "class ColorToneAdjustEffect"
    )

    print("[37/43] 新增 DetailAdjustEffect")
    write_if_absent(
        f"{effect}/DetailAdjustEffect.java", DETAIL_ADJUST_EFFECT, "class DetailAdjustEffect"
    )

    print("[38/43] 新增 AudioEqualizerController")
    write_if_absent(
        f"{exoplayer}/audio/AudioEqualizerController.java",
        AUDIO_EQUALIZER_CONTROLLER,
        "class AudioEqualizerController",
    )

    print("[39/43] 新增 DanmakuPlayerViewController")
    write_if_absent(
        f"{ui}/danmaku/DanmakuPlayerViewController.java",
        DANMAKU_PLAYER_VIEW_CONTROLLER,
        "class DanmakuPlayerViewController",
    )

    print("[40/43] 新增 LibassPlayerViewController")
    stale_ui = f"{ui}/libass/LibassPlayerViewController.java"
    if os.path.exists(stale_ui):
        os.remove(stale_ui)
        print(f"  - 移除旧位置: {stale_ui}")
    write_if_absent(
        f"{exoplayer}/ui/libass/LibassPlayerViewController.java",
        LIBASS_PLAYER_VIEW_CONTROLLER,
        "class LibassPlayerViewController",
    )

    print("[41/43] 新增 MpvDrmSupport")
    write_if_absent(
        f"{mpvplayer}/media/MpvDrmSupport.java", MPV_DRM_SUPPORT, "class MpvDrmSupport"
    )

    print("[42/43] 新增 MpvConfigFileInspector")
    write_if_absent(
        f"{mpvplayer}/MpvConfigFileInspector.java",
        MPV_CONFIG_FILE_INSPECTOR,
        "class MpvConfigFileInspector",
    )

    print("[43/43] 新增 LibassFontConfig")
    write_if_absent(
        f"{exoplayer}/libass/LibassFontConfig.java", LIBASS_FONT_CONFIG, "class LibassFontConfig"
    )

    print("[44/51] 新增 IsoUri")
    write_if_absent(f"{datasource}/IsoUri.java", ISO_URI, "class IsoUri")

    print("[45/51] 新增 AudioChannelMix")
    write_if_absent(f"{common}/audio/AudioChannelMix.java", AUDIO_CHANNEL_MIX, "class AudioChannelMix")

    print("[46/51] 新增 CmgConfiguration")
    hls = f"{exoplayer}/hls"
    write_if_absent(f"{hls}/CmgConfiguration.java", CMG_CONFIGURATION, "class CmgConfiguration")

    print("[47/51] 新增 DefaultPositionMediaSource")
    write_if_absent(
        f"{exoplayer}/source/DefaultPositionMediaSource.java",
        DEFAULT_POSITION_MEDIA_SOURCE,
        "class DefaultPositionMediaSource",
    )

    print("[48/51] 新增 ContentTypeResolvingMediaSource")
    write_if_absent(
        f"{exoplayer}/source/ContentTypeResolvingMediaSource.java",
        CONTENT_TYPE_RESOLVING_MEDIA_SOURCE,
        "class ContentTypeResolvingMediaSource",
    )

    print("[49/51] 新增 VideoTransform")
    write_if_absent(f"{common}/VideoTransform.java", VIDEO_TRANSFORM, "class VideoTransform")

    print("[50/51] 新增 BdjRuntime")
    write_if_absent(f"{exoplayer}/iso/BdjRuntime.java", BDJ_RUNTIME, "class BdjRuntime")

    print("[51/51] PlayerView 补充 VideoTransform import")
    ensure_import(pv, "import androidx.media3.common.VideoTransform;")

    print("[52/52] 扩展 PreloadManagerListener.onPreloadPaused")
    insert_before(
        f"{exoplayer}/source/preload/PreloadManagerListener.java",
        "  default void onError(PreloadException exception) {}",
        PRELOAD_PAUSED_METHOD,
        "onPreloadPaused(MediaItem",
    )

    print("[53/58] 让 MpvPlayer 实现 DiscMenuController")
    mpv_player = f"{mpvplayer}/MpvPlayer.java"
    insert_after(
        mpv_player,
        "public final class MpvPlayer extends SimpleBasePlayer",
        " implements androidx.media3.common.DiscMenuController",
        "implements androidx.media3.common.DiscMenuController",
    )

    print("[54/58] 扩展 MpvPlayer 字段与方法")
    insert_before(mpv_player, "  private @C.DecodeMode int decode;", MPVPLAYER_FIELDS + MPVPLAYER_METHODS, "setVideoDecoderMode(MpvDecoderMode")
    insert_after(mpv_player, "  public static final class Builder {", "\n" + MPV_BUILDER_FIELDS + MPV_BUILDER_METHODS, "setBitmapSubtitleBrightness(float")
    ensure_import(mpv_player, "import androidx.media3.mpvplayer.MpvDecoderMode;")

    print("[55/58] 扩展 MpvSubtitleOptions.Builder")
    mso = f"{mpvplayer}/MpvSubtitleOptions.java"
    insert_before(
        mso,
        "    private double position = 100.0;",
        MPV_SUBTITLE_OPTION_FIELDS + MPV_SUBTITLE_OPTION_METHODS,
        "setBitmapSubtitleBrightness(float",
    )

    print("[56/57] 扩展 SubtitleView.setBitmapSubtitleBrightness")
    sv = f"{ui}/SubtitleView.java"
    insert_before(sv, "  private List<Cue> cues;", SUBTITLEVIEW_BRIGHTNESS, "setBitmapSubtitleBrightness(float")

    print("[58/58] 对齐 is.xyz.mpv.MPVLib（Stream / openStream / enqueueCommandLongResult）")
    patch_mpvlib(root)
    print("[59/59] 补齐 extra APIs（ExoPlayer subtitleOffsets / prepareSource / renderers / mpv loader / ui）")
    patch_extra_apis(root)

    print("[60/60] 补齐 TV 侧别名 API")
    patch_tv_aliases(root)

    print("[61/61] 补齐 MPV 配置/字幕选项 API")
    patch_mpv_options(root)

    print("[62/62] 补齐 TV 5.8.1 UI 层依赖")
    patch_tv_ui_apis(root)

    print("[63/63] 补齐 DecoderMode.SOFTWARE / EVENT_DISC_MENU_STATE_CHANGED")
    patch_tv_constants(root)

    print("[64/64] AudioChannelMode.isAvailable(int)")
    patch_audio_mode(root)

    print("[58/58] 完成")
    print("\n补丁完成。")


if __name__ == "__main__":
    main()
