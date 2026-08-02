package com.sajang.dama.next

import android.content.Context
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

internal object YtDlpRuntime {
    private const val PREFS = "yt_dlp_runtime"
    private const val LAST_UPDATE_ATTEMPT = "last_update_attempt"
    private const val UPDATE_INTERVAL_MILLIS = 24L * 60L * 60L * 1_000L

    private val initMutex = Mutex()
    private val updateMutex = Mutex()

    @Volatile
    private var initialized = false

    suspend fun ensureReady(context: Context) {
        if (initialized) return
        initMutex.withLock {
            if (initialized) return
            val appContext = context.applicationContext
            YoutubeDL.getInstance().init(appContext)
            FFmpeg.getInstance().init(appContext)
            initialized = true
        }
    }

    suspend fun updateIfDue(context: Context) {
        updateMutex.withLock {
            val appContext = context.applicationContext
            val preferences = appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val now = System.currentTimeMillis()
            val lastAttempt = preferences.getLong(LAST_UPDATE_ATTEMPT, 0L)
            if (now - lastAttempt < UPDATE_INTERVAL_MILLIS) return

            preferences.edit().putLong(LAST_UPDATE_ATTEMPT, now).apply()
            runCatching {
                YoutubeDL.getInstance().updateYoutubeDL(
                    appContext,
                    YoutubeDL.UpdateChannel.STABLE
                )
            }
        }
    }
}
