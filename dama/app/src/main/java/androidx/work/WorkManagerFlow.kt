package androidx.work

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.withContext
import java.util.UUID

fun WorkManager.getWorkInfoByIdFlow(id: UUID): Flow<WorkInfo?> = flow {
    while (true) {
        val info = withContext(Dispatchers.IO) {
            getWorkInfoById(id).get()
        }
        emit(info)
        if (info?.state?.isFinished == true) break
        delay(500)
    }
}
