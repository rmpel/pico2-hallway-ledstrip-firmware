<?php

$cache_dir = __DIR__ . '/development_cache';

if ( ! is_dir( $cache_dir ) ) {
	mkdir( $cache_dir );
}

$request = $_GET['request'];
// request should be in the form of 'api/[a-z]+'

$request_op = 'unknown';
preg_match( '@api/([a-z]+)@', $request, $matches );
$request_op     = $matches[1];
$request_method = $_SERVER['REQUEST_METHOD'];

$request_selector = $request_method . ':' . $request_op;

function post_data( $key = null ) {
	// $raw_post
	$raw_post = file_get_contents( 'php://input' );
	$POST     = $_POST ?? [];
	if ( ! empty( $raw_post ) ) {
		$POST = json_decode( $raw_post, true );
	}

	return $key ? ( $POST[ $key ] ?? '' ) : $POST;
}

switch ( $request_selector ) {
	case 'GET:config':
		serve_from_cache( 'config.json' );
		break;
	case 'GET:status':
		update_status();
		serve_from_cache( 'status.json' );
		break;
	case 'POST:config':
		$new_config         = post_data();
		$old_config         = read_from_cache( 'config.json' );
		$new_config['mode'] = $old_config['mode'];
		update_cache( 'config.json', $new_config, true );
	case 'POST:mode':
		$mode = post_data( 'mode' );
		if ( ! in_array( $mode, [ 'on', 'off', 'auto', 'rainbow' ] ) ) {
			$mode = 'on';
		}
		update_cache( 'config.json', [ 'mode' => $mode ], true );
}

function serve_from_cache( $filename ) {
	global $cache_dir;
	header( 'Content-type: application/json' );
	header( 'Cache-Control: no-cache' );
	header( 'Pragma: no-cache' );
	readfile( $cache_dir . '/' . $filename );
}

function read_from_cache( $filename ) {
	global $cache_dir;

	return json_decode( file_get_contents( $cache_dir . '/' . $filename ), true );
}

function write_to_cache( $filename, $data ) {
	global $cache_dir;
	file_put_contents( $cache_dir . '/' . $filename, json_encode( $data, 192 ) );
}

function update_cache( $filename, $data, $single_value = false ) {
	global $cache_dir;
	$cache = read_from_cache( $filename );
	if ( $single_value ) {
		$cache = array_merge( $cache, $data );
	} else {
		$cache = array_merge_recursive( $cache, $data );
	}
	write_to_cache( $filename, $cache );
}

function update_status() {
	$status = read_from_cache( 'status-original.json' );
	$config = read_from_cache( 'config.json' );
	// get schedule, sort by time
	// determine current time
	// build 'upcoming_events' based on time; next steps first, then steps that already past.
	/* sample:
	{
            "brightness": 0,
            "hue": 0,
            "saturation": 0,
            "time": "16:29"
        }
	becomes
	{
                "step" : {
                    "brightness" : 0,
                    "hue" : 0,
                    "saturation" : 0,
                    "time" : "16:29"
                },
                "time" : 59340,
                "seconds_until" : 16429
            }
	*/
	// set next_step as first of upcoming_events
	// set current_step as last of all events, after sorting

	$timezone = $config['location']['timezone'];
	ini_set( 'date.timezone', $timezone );
	$sun_info = date_sun_info( time(), $config['location']['latitude'], $config['location']['longitude'] );
	$sunrise  = date( 'H:i', $sun_info['sunrise'] );
	$sunset   = date( 'H:i', $sun_info['sunset'] );

	$status['current_time'] = date( 'H:i:s' );

	$status['sun_times']['sunrise'] = $sunrise;
	$status['sun_times']['sunset']  = $sunset;

	$status['ntp'] = [
		'last_sync_seconds_ago' => 0,
		'synced'                => true,
	];

	$status['manual'] = $config['manual'];

	$status['current_time_seconds'] = time() - strtotime( 'today' );

	$status['mode'] = $config['mode'];

	$status['schedule_info'] = build_schedule( $config, $sun_info );

	write_to_cache( 'status.json', $status );
}

function build_schedule( $config, $sun_info ) {
	$schedule = [
		'next_step'             => [],
		'progress'              => 0.0,
		'upcoming_events'       => [],
		'current_step'          => [],
		'next_event_in_seconds' => 0,
	];

	$schedule_sorted = $config['schedule'];
	$times           = [];
	foreach ( $schedule_sorted as &$value ) {
		if ( isset( $value['event'] ) ) {
			$sun_time = $sun_info[ $value['event'] ] + ( $value['offset'] * 60 );
		}
		$value['calculated_time'] = array_key_exists( 'time', $value ) ? strtotime( $value['time'] ) : $sun_time;

		$times[] = $value['calculated_time'];
	}
	unset( $value );
	array_multisort( $times, SORT_ASC, $schedule_sorted );

	$schedule_shifted = [];
	$schedule_passed  = [];
	foreach ( $schedule_sorted as $key => $value ) {
		$scheduled_item = [
			'step'          => $value,
			'time'          => $value['calculated_time'] - strtotime( 'today' ),
			'seconds_until' => $value['calculated_time'] - time(),
		];
		if( $scheduled_item['seconds_until'] < 0 ) {
			$scheduled_item['seconds_until'] += 86400;
		}
		unset( $scheduled_item['step']['calculated_time'] );
		if ( $value['calculated_time'] > time() ) {
			$schedule_shifted[] = $scheduled_item;
		} else {
			$schedule_passed[] = $scheduled_item;
		}
	}

	// add passed at the end
	foreach ( $schedule_passed as $key => $value ) {
		$schedule_shifted[] = $value;
	}

	$schedule['upcoming_events'] = $schedule_shifted;
	$schedule['current_step']    = array_pop( $schedule_shifted );
	$schedule['next_step']       = array_shift( $schedule_shifted );

	$progress_slot        = $schedule['next_step']['time'] - $schedule['current_step']['time'];
	$progress_pointer     = time() - $schedule['current_step']['time'];
	$schedule['progress'] = $progress_pointer / $progress_slot;

	$schedule['next_event_in_seconds'] = $schedule['next_step']['seconds_until'];

	return $schedule;
}
