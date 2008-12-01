-ifdef(PROF).
-define(prof(Key, Label),
        profile_server:step(Key, Label, ?MODULE, ?LINE)).
-else.
-define(prof(Key, Label), true).
-endif.
